# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Attach the recovery rule to the salary structures that already exist."""
    env['hr.payroll.structure'].with_context(active_test=False).search([])._ftp_add_salary_advance_rule()
