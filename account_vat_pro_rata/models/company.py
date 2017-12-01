# -*- coding: utf-8 -*-
# © 2017 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    default_vat_prorata_journal_id = fields.Many2one(
        'account.journal', string='Default VAT Pro Rata Journal',
        copy=False)
