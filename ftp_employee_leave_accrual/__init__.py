# -*- coding: utf-8 -*-
from . import models
from .models.leave_policy_setup import setup_leave_policy


def post_init_hook(env):
    """Create the leave types and accrual plans the policy needs.

    Done here rather than in XML data so existing records are reused: a
    database that already has a Casual Leave type keeps it instead of gaining
    a second one. Runs per company, so a multi-company database gets its own
    types, plans and settings for each.
    """
    for company in env['res.company'].search([]):
        setup_leave_policy(env, company)
