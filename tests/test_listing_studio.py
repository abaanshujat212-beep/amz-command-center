import pytest

from services.listings.studio import create_draft_version, create_project, review_draft


class NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid input must fail before database access")


def test_viewers_cannot_create_projects_or_drafts():
    with pytest.raises(PermissionError):
        create_project(
            NoDatabase(), tenant_id="t", actor_user_id="u", actor_role="viewer", name="A"
        )
    with pytest.raises(PermissionError):
        create_draft_version(
            NoDatabase(),
            tenant_id="t",
            project_id="p",
            actor_user_id="u",
            actor_role="viewer",
            title="",
            bullets=[],
            description="",
            backend_terms=[],
            product_fact_ids=[],
            change_summary="initial",
        )


def test_ai_assisted_draft_requires_generation_provenance():
    with pytest.raises(ValueError, match="generation provenance"):
        create_draft_version(
            NoDatabase(),
            tenant_id="t",
            project_id="p",
            actor_user_id="u",
            actor_role="analyst",
            title="Draft",
            bullets=[],
            description="",
            backend_terms=[],
            product_fact_ids=[],
            change_summary="AI pass",
            origin="ai_assisted",
        )


def test_only_managers_can_approve_or_request_changes():
    with pytest.raises(PermissionError):
        review_draft(
            NoDatabase(),
            tenant_id="t",
            project_id="p",
            draft_version_id="d",
            actor_user_id="u",
            actor_role="analyst",
            decision="approved",
        )


def test_unknown_review_decision_fails_closed():
    with pytest.raises(ValueError, match="decision"):
        review_draft(
            NoDatabase(),
            tenant_id="t",
            project_id="p",
            draft_version_id="d",
            actor_user_id="u",
            actor_role="owner",
            decision="publish_to_amazon",
        )
