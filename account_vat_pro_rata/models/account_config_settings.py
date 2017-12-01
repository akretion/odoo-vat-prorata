# -*- coding: utf-8 -*-
# © 2017 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class AccountConfigSettings(models.TransientModel):
    _inherit = 'account.config.settings'

    default_vat_prorata_journal_id = fields.Many2one(
        related='company_id.default_vat_prorata_journal_id')
