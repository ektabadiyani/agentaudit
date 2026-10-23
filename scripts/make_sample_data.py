"""Generate the synthetic Tasktide conversations and their reference labels.

Every conversation is invented. The reference labels are the verdicts each answer was
written to have, which makes them a known answer key for testing the grader. For a real
audit, replace them with a human's independent grades.
"""

import csv
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "sample"

# (id, topic, question, ai_answer, handed_off, reopened_within_7d, csat, reference_verdict)
ROWS = [
    ("c01", "billing", "How much is the Team plan if we pay yearly?",
     "Team is $12 per member per month, and paying annually saves 20%, so it works out to $9.60 per member per month, billed yearly. Prices exclude sales tax or VAT.",
     False, False, 5, "correct"),
    ("c02", "billing", "I bought an annual plan 3 weeks ago and want to cancel. Can I get a refund?",
     "Yes! Annual plans can be refunded in full within 30 days of purchase. Cancel from Settings > Billing > Cancel plan and the refund will go back to your card.",
     False, True, 1, "incorrect"),
    ("c03", "billing", "If I cancel my monthly plan halfway through the month, do I get money back for the rest of it?",
     "We don't refund partial months. Your plan stays active until the end of the current billing month and then moves to the Free plan.",
     False, False, 3, "correct"),
    ("c04", "billing", "We removed 4 seats yesterday. Will we get a refund?",
     "The unused time on removed seats is credited to your next invoice rather than refunded to your card.",
     False, False, 4, "correct"),
    ("c05", "billing", "We're a registered nonprofit. Can we get the nonprofit discount on top of annual pricing?",
     "Absolutely. Nonprofits get 50% off, and you can combine it with the 20% annual discount for the best possible price.",
     False, False, 5, "incorrect"),
    ("c06", "billing", "Can you reissue last month's invoice with our new company name?",
     "You can update your company name under Settings > Billing > Billing details, and it will appear on your invoices.",
     False, True, 2, "partial"),
    ("c07", "billing", "How do I add 3 more people, and when will I be charged?",
     "Go to Settings > Billing > Seats to add them. New seats are charged immediately, pro-rated by day for the rest of your billing period.",
     False, False, 5, "correct"),
    ("c08", "billing", "Do guests count as paid seats?",
     "No, guests are free. Each paid seat includes up to 5 guests, who can view and comment on the projects they're invited to.",
     False, False, 5, "correct"),
    ("c09", "billing", "Is there a discount for early-stage startups?",
     "Yes! Startups under 2 years old get 30% off their first year through the Tasktide Startup Program. Just reply with your incorporation date to apply.",
     False, False, 5, "unsupported"),
    ("c10", "billing", "Do your prices include VAT?",
     "Prices are in US dollars and exclude applicable sales tax or VAT.",
     False, False, 4, "correct"),
    ("c11", "account_access", "My password reset link says it has expired. I clicked it about an hour after it arrived.",
     "Reset links expire after 30 minutes and can only be used once. Request a new one from Forgot password on the sign-in page and use it within 30 minutes.",
     False, False, 4, "correct"),
    ("c12", "account_access", "Our company signs in to Tasktide through Okta. How do I reset my Tasktide password?",
     "Click Forgot password on the sign-in page and enter your email. We'll send you a reset link that's valid for 30 minutes.",
     False, True, 1, "incorrect"),
    ("c13", "account_access", "I lost my phone with the authenticator app. I'm a regular member of the workspace.",
     "If you saved backup codes, sign in with one and set up 2FA again on your new phone. If not, ask a workspace owner to reset your 2FA from Settings > Members.",
     False, False, 5, "correct"),
    ("c14", "account_access", "I'm the workspace owner. I lost my 2FA device and my backup codes. Can you reset it right now?",
     "I'm not able to reset 2FA over chat. I'm connecting you with our support team, who will verify your identity first. This usually takes 1 to 2 business days.",
     True, False, 4, "correct"),
    ("c15", "account_access", "Workspace owner here, lost my 2FA phone and I don't have backup codes.",
     "No problem! I've just sent a 2FA reset link to your email address. Click it to turn off 2FA, then sign in and set it up again.",
     False, True, 1, "incorrect"),
    ("c16", "account_access", "Our workspace owner left the company. How do we take over the account?",
     "An admin can contact support. We'll need written confirmation from someone with authority over the account, such as a manager on company letterhead, and the process takes 3 to 5 business days.",
     False, False, 4, "correct"),
    ("c17", "account_access", "How do I transfer ownership of the workspace to my colleague?",
     "Go to Settings > Members > Transfer ownership and choose your colleague as the new owner.",
     False, True, 3, "partial"),
    ("c18", "account_access", "I never received the password reset email.",
     "Please check your spam folder and confirm you're using the email address on your Tasktide account. If it hasn't arrived within 10 minutes, request a new link.",
     False, False, 4, "correct"),
    ("c19", "data", "How do I export everything from our workspace? We're on the Team plan.",
     "Full workspace export is only available on the Business plan. On Team you can export each project as a CSV from the project's ⋯ menu > Export. Comments and attachments aren't included in CSV exports.",
     False, False, 4, "correct"),
    ("c20", "data", "Can I export a project including all the comments?",
     "Yes. Open the project, click ⋯ > Export and choose CSV. The file includes tasks, comments and attachments.",
     False, True, 2, "incorrect"),
    ("c21", "data", "I accidentally deleted a project last week. Can I get it back?",
     "Yes. Deleted projects stay in Trash for 30 days, and any project admin can restore them from there.",
     False, False, 5, "correct"),
    ("c22", "data", "We deleted our workspace by mistake 10 days ago. Can support restore it?",
     "I'm sorry. Support can restore a workspace within 7 days of deletion, but after 7 days the deletion is permanent and can't be undone, even by our team.",
     False, False, 2, "correct"),
    ("c23", "data", "The download link for our workspace export doesn't work anymore.",
     "Export links expire after 24 hours. A workspace owner can request a fresh export from Settings > Data > Export workspace, and we'll email a new link.",
     False, False, 4, "correct"),
    ("c24", "data", "If we delete our workspace, does that stop the billing?",
     "Yes, deleting the workspace automatically cancels your subscription, so you won't be charged again.",
     False, False, 5, "incorrect"),
    ("c25", "data", "Can I export my data in Excel format?",
     "Projects export as CSV, which opens in Excel. Business customers can also choose a native .xlsx export that keeps your formatting.",
     False, False, 4, "unsupported"),
    ("c26", "integrations", "Does Tasktide integrate with Salesforce?",
     "There's no native Salesforce integration, but you can connect Tasktide to Salesforce through Zapier on any paid plan.",
     False, False, 4, "correct"),
    ("c27", "integrations", "If we use the Jira import, will Jira and Tasktide stay in sync?",
     "The Jira import is available on Team and Business plans and brings your Jira projects into Tasktide.",
     False, True, 2, "partial"),
    ("c28", "integrations", "Can I use the Slack integration on the Free plan?",
     "Yes, the Slack integration is available on every plan, including Free.",
     False, True, 1, "incorrect"),
    ("c29", "integrations", "Do you integrate with Microsoft Teams?",
     "Yes! Our Microsoft Teams app lets you get task notifications and create tasks from chats. It's included on Team and Business plans.",
     False, False, 5, "unsupported"),
    ("c30", "reliability", "There was an outage yesterday and we're on Business. Can we get a credit?",
     "Business includes a 99.9% monthly uptime SLA. If uptime fell below that this month, you can ask support for a service credit of 10% of the month's fee within 30 days after the month ends. Credits apply to a future invoice.",
     False, False, 4, "correct"),
    ("c31", "reliability", "We're on the Team plan and yesterday's outage cost us hours. Is there any compensation?",
     "I'm sorry about the disruption. Team customers can request a service credit of 10% of the monthly fee within 30 days.",
     False, True, 2, "incorrect"),
    ("c32", "reliability", "Where can I check whether Tasktide is down?",
     "Check status.tasktide.example. You can also subscribe there to get incident updates.",
     False, False, 5, "correct"),
    ("c33", "reliability", "We qualify for an SLA credit on Business. Can it be refunded to our card instead?",
     "Yes, we can issue the service credit as a refund to your card. It'll arrive within 5 to 10 business days.",
     False, False, 5, "incorrect"),
    ("c34", "billing", "How much is the Business plan?",
     "Great question! Let me connect you with our sales team, who can walk you through Business pricing.",
     True, False, 3, "partial"),
]

with open(OUT / "conversations.jsonl", "w", encoding="utf-8") as f:
    for cid, topic, q, a, handed_off, reopened, csat, _ in ROWS:
        f.write(json.dumps({"id": cid, "topic": topic, "question": q, "ai_answer": a,
                            "handed_off": handed_off, "reopened_within_7d": reopened, "csat": csat}) + "\n")

with open(OUT / "reference_labels.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["conversation_id", "verdict"])
    writer.writerows((row[0], row[-1]) for row in ROWS)

print(f"Wrote {len(ROWS)} conversations to {OUT}")
