"""Test questions with known answers, checked by hand against the handbook.

Every expected value was read from the PDF itself (page noted), not copied
from the agent's output. Run them with `python run_eval.py`.

Fields:
  id            short unique name, used with --only
  question      what the employee asks
  history       earlier questions in the same chat (asked for real first,
                so follow-up handling is tested end to end)
  must_include  every item must appear in the answer; an item that is a
                list passes if ANY of its alternatives appears
  must_not      none of these may appear
  sources       each string must appear in one of the listed source subjects
  no_sources    True for questions the handbook doesn't answer: the agent
                must list no sources and point the employee to HR
"""

REFER_TO_HR = [["HR", "Human Resources"]]

CASES = [
    # ---- Single-section facts ---------------------------------------------
    {"id": "gift_limit",  # p. 10
     "question": "Is there a limit on gifts I can accept?",
     "must_include": ["$200"], "sources": ["Code of Ethics"]},
    {"id": "arrest_reporting",  # p. 14
     "question": "How soon do I have to report an arrest?",
     "must_include": [["48 hours", "48-hour"]], "sources": ["Arrests"]},
    {"id": "fmla_eligibility",  # p. 15
     "question": "Who is eligible for family and medical leave?",
     "must_include": ["1,250", ["one (1) year", "one year", "1 year"]],
     "sources": ["Family & Medical Leave"]},
    {"id": "fmla_length",  # p. 15
     "question": "How much FMLA leave can I take, and is it paid?",
     "must_include": [["twelve", "12"], "unpaid"], "sources": ["Family & Medical Leave"]},
    {"id": "outside_employment",  # p. 17
     "question": "Can I have a second job, and how many hours can I work there?",
     "must_include": ["24 hours"], "sources": ["Outside Employment"]},
    {"id": "resignation_notice",  # p. 18
     "question": "How much notice do I have to give when I quit?",
     "must_include": [["two weeks", "2 weeks"]], "sources": ["Separation"]},
    {"id": "smoking_distance",  # p. 19
     "question": "How far from a building entrance do I have to be to smoke?",
     "must_include": ["30 feet"], "sources": ["Smoking"]},
    {"id": "mandatory_training",  # p. 16
     "question": "How often do I have to redo the mandatory compliance training?",
     "must_include": [["two years", "2 years"]], "sources": ["Mandatory Compliance Training"]},
    {"id": "job_references",  # p. 16
     "question": "Can I give a job reference for a former coworker?",
     "must_include": [["not authorized", "no city employee", "cannot", "can't"]],
     "sources": ["Job References"]},
    {"id": "vehicle_accident",  # p. 18
     "question": "Who do I call after an accident in a City vehicle?",
     "must_include": ["229-0291"], "sources": ["Safety"]},
    {"id": "drug_testing",  # p. 20
     "question": "When can the City make me take a drug test?",
     "must_include": ["reasonable suspicion"], "sources": ["Drugs and Alcohol"]},
    {"id": "employee_of_month",  # p. 14
     "question": "Who can be nominated for Employee of the Month?",
     "must_include": ["Division Manager"], "sources": ["Recognition"]},
    {"id": "council_meetings",  # p. 6
     "question": "When does the City Council meet?",
     "must_include": ["first and third Wednesday"], "sources": ["Government Structure"]},
    {"id": "job_postings",  # p. 17
     "question": "What system does the City use to post job openings?",
     "must_include": [["NEO GOV", "NEOGOV"]], "sources": ["Promotional"]},
    {"id": "training_contact",  # p. 19
     "question": "Who do I contact about training classes?",
     "must_include": ["229-6501"], "sources": ["Staff Development"]},

    # ---- Sections that run onto the next page -----------------------------
    # "Workers' Compensation" starts mid-page 20 and continues on page 21,
    # where the C-1 form and the HR phone number are.
    {"id": "injury_form",  # p. 21
     "question": "What form do I fill out if I'm hurt on the job?",
     "must_include": ["C-1"], "sources": ["Workers' Compensation"]},
    {"id": "workers_comp_phone",  # p. 21
     "question": "What number do I call with workers' comp questions?",
     "must_include": ["229-5048"], "sources": ["Workers' Compensation"]},

    # ---- Grounded partial answer ------------------------------------------
    # The handbook gives no day count for military leave; it points to NRS 281.
    {"id": "military_leave_days",  # p. 16
     "question": "How many days of military leave am I entitled to?",
     "must_include": ["NRS 281"], "sources": ["Military Leave"]},

    # ---- Follow-ups (history is asked for real first) ---------------------
    {"id": "followup_fmla_notice",  # p. 15
     "history": ["Who is eligible for family and medical leave?"],
     "question": "how much notice do I need to give?",
     "must_include": [["30 days", "thirty (30) days", "thirty days"]],
     "sources": ["Family & Medical Leave"]},
    {"id": "followup_vapes",  # p. 19
     "history": ["What is the policy on smoking?"],
     "question": "does that apply to vapes too?",
     "must_include": ["electronic"], "sources": ["Smoking"]},

    # ---- Not in the handbook: must refuse, not guess ----------------------
    {"id": "refuse_dog", "question": "Can I bring my dog to work?",
     "no_sources": True, "must_include": REFER_TO_HR},
    {"id": "refuse_stock_options", "question": "Do City employees get stock options?",
     "no_sources": True, "must_include": REFER_TO_HR},
    {"id": "refuse_weather", "question": "What is the weather like in Las Vegas?",
     "no_sources": True, "must_include": REFER_TO_HR},
]
