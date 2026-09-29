"""Shared name utilities."""

NICKNAMES = {
    "Robert": "Bob", "William": "Bill", "James": "Jim", "Richard": "Dick", "Michael": "Mike",
    "Elizabeth": "Liz", "Margaret": "Peggy", "Patricia": "Pat", "Jennifer": "Jen", "Christopher": "Chris",
    "Kimberly": "Kim", "Deborah": "Debbie", "Susan": "Sue", "Thomas": "Tom", "Daniel": "Dan",
    "Joseph": "Joe", "Kenneth": "Ken", "Donald": "Don", "Anthony": "Tony", "Matthew": "Matt",
}

CANON_FIRST = {v.lower(): k.lower() for k, v in NICKNAMES.items()}
