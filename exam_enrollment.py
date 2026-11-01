"""Shared subject-wise eligibility; historical marked results remain evidence."""


def enrolled(award,paper,details):
    if award.data.get('student_filter','class')!='subject':return True
    subjects=(details or {}).get('subjects',[])
    return isinstance(subjects,(list,tuple)) and paper.get('subject') in subjects


def recorded(score):
    return score is not None and (score.state in ('A','L') or getattr(score,'obtained',None) is not None or getattr(score,'value',None) is not None)


def included(award,paper,details,score):return enrolled(award,paper,details) or recorded(score)
