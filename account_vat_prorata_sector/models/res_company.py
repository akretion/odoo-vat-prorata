# Copyright 2017-2022 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    vat_prorata = fields.Boolean(string='Company has VAT Prorata', default=True)
    vat_prorata_journal_id = fields.Many2one(
        'account.journal', string='Default VAT Pro Rata Journal',
        copy=False, check_company=True)
