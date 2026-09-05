export type CopilotQuestion = { key:string; question:string; questionUr:string; tier:"T1"|"T2"; intent:string }
export const COPILOT_QUESTIONS: CopilotQuestion[] = [
	{ key:"account_last_7_days", question:"How much did we spend in the last 7 settled days, and what was ACOS?", questionUr:"Pichhle 7 settled din mein kitna kharch hua aur ACOS kya raha?", tier:"T1", intent:"Account KPI read" },
	{ key:"budget_throttled_campaigns", question:"Which campaigns are being throttled by their budget?", questionUr:"Kaun se campaigns apne budget ki wajah se ruk rahe hain?", tier:"T1", intent:"Budget diagnosis" },
	{ key:"keywords_burning_without_sales", question:"Which keywords spent money over 30 days with no orders at all?", questionUr:"Kaun se keywords ne 30 din mein paisa jalaya magar ek bhi order nahi diya?", tier:"T1", intent:"Waste detection" },
	{ key:"negate_candidates", question:"Which search terms look worth negating?", questionUr:"Kaun se search terms negative karne layak lagte hain?", tier:"T2", intent:"Proposal only" },
	{ key:"harvest_candidates", question:"Which search terms are converting but not yet exact keywords?", questionUr:"Kaun se search terms convert ho rahe hain magar exact keyword nahi bane?", tier:"T2", intent:"Harvest proposal" },
	{ key:"product_opportunities", question:"Which products have the strongest opportunity score and profit room?", questionUr:"Kaun se products ka opportunity score aur profit room sab se strong hai?", tier:"T1", intent:"Product opportunity" },
	{ key:"sqp_harvest_opportunities", question:"Which SQP queries should we harvest or test first?", questionUr:"Kaun si SQP queries pehle harvest ya test karni chahiye?", tier:"T2", intent:"SQP proposal" },
	{ key:"data_freshness", question:"How fresh is the data, and is any dataset stale?", questionUr:"Data kitna taza hai, koi dataset purana reh gaya hai?", tier:"T1", intent:"Pipeline health" },
	{ key:"decision_history", question:"How many actions were approved, rejected or expired?", questionUr:"Kitne actions approve, reject ya expire hue?", tier:"T1", intent:"Decision audit" },
	{ key:"rule_state", question:"Which rules exist, and which are actually live?", questionUr:"Kaun se rules hain, aur un mein se kaun sach mein chal rahe hain?", tier:"T1", intent:"Rule state" },
	{ key:"economics_gaps", question:"Where is cost data missing, so profit rules cannot run?", questionUr:"Kahan cost data missing hai, jis se profit rules chal nahi sakte?", tier:"T1", intent:"Economics gap" },
	{ key:"pipeline_health", question:"Did the pipelines run, and did any fail this week?", questionUr:"Is hafte pipelines chale, koi fail hua?", tier:"T1", intent:"Run history" },
]
