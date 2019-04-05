# -*- coding: utf-8 -*-
# Copyright 2017-2018 Akretion
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models, api, _
from odoo.tools import float_compare, float_is_zero, float_round
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta


class AccountVatProrata(models.Model):
    _name = 'account.vat.prorata'
    _description = 'VAT Pro Rata calculation'
    _inherit = ['mail.thread']
    _order = 'date_to desc'

    @api.model
    def default_get(self, fields_list):
        res = super(AccountVatProrata, self).default_get(fields_list)
        today_str = fields.Date.context_today(self)
        today_dt = fields.Date.from_string(today_str)
        date_from_dt = today_dt + relativedelta(months=-1) +\
            relativedelta(month=1, day=1)
        date_to_dt = today_dt + relativedelta(day=1) + relativedelta(days=-1)
        company = self.env.user.company_id
        jl_id = self.env.user.company_id.default_vat_prorata_journal_id.id\
            or False
        source_jrls = self.env['account.journal'].search([
            ('type', '=', 'purchase'), ('company_id', '=', company.id)])
        ratio_source_jrls = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', company.id)])
        # For those who use the module account_tax_cash_basis
        if (
                hasattr(company, 'tax_cash_basis_journal_id') and
                company.tax_cash_basis_journal_id):
            source_jrls |= company.tax_cash_basis_journal_id
        res.update({
            'date_from': fields.Date.to_string(date_from_dt),
            'date_to': fields.Date.to_string(date_to_dt),
            'journal_id': jl_id,
            'source_journal_ids': source_jrls.ids,
            'ratio_source_journal_ids': ratio_source_jrls.ids,
            'move_label': _('VAT Pro Rata'),
        })
        return res

    date_from = fields.Date(
        string="Date From",
        required=True, readonly=True, states={'draft': [('readonly', False)]},
        track_visibility='onchange')
    date_to = fields.Date(
        string="Date To",
        required=True, readonly=True, states={'draft': [('readonly', False)]},
        copy=False, track_visibility='onchange')
    ratio_source_journal_ids = fields.Many2many(
        'account.journal',
        'account_vat_prorata_ratio_journal_rel', 'vat_prorata_id',
        'journal_id', string='Compute Ratio Source Journals',
        readonly=True, states={'draft': [('readonly', False)]},
        required=True)
    target_move = fields.Selection([
        ('posted', 'All Posted Entries'),
        ('all', 'All Entries')],
        string='Target Moves', required=True, default='all',
        readonly=True, states={'draft': [('readonly', False)]},
        track_visibility='onchange')
    source_journal_ids = fields.Many2many(
        'account.journal', string='Source Journals', readonly=True,
        states={'draft': [('readonly', False)]}, required=True)
    journal_id = fields.Many2one(
        'account.journal', string='VAT Pro Rata Journal', required=True,
        states={'done': [('readonly', True)]})
    move_id = fields.Many2one(
        'account.move', string='VAT Pro Rata Entry', readonly=True,
        copy=False)
    move_label = fields.Char(
        string='Label of the VAT Pro Rata Entry', required=True,
        states={'done': [('readonly', True)]},
        help="This label will be written in the 'Name' field of the "
        "VAT Pro Rata Journal Items and in the 'Reference' field of "
        "the Journal Entry.")
    line_ids = fields.One2many(
        'account.vat.prorata.line', 'parent_id', string='VAT Pro Rata Lines',
        readonly=True)
    subject_line_ids = fields.One2many(
        'account.vat.prorata.subject.line', 'parent_id',
        domain=[('vat_subject', '=', 'vat_subject')],
        string='VAT Subject Accounts', readonly=True)
    nosubject_line_ids = fields.One2many(
        'account.vat.prorata.subject.line', 'parent_id',
        domain=[('vat_subject', '=', 'no_vat_subject')],
        string='No VAT Subject Accounts', readonly=True)
    computed_perct = fields.Float(
        string='VAT Subject Computed Ratio', readonly=True,
        track_visibility='onchange')
    used_perct = fields.Float(
        string='VAT Subject Used Ratio', track_visibility='onchange',
        states={'done': [('readonly', True)]})
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        states={'done': [('readonly', True)]},
        default=lambda self: self.env['res.company']._company_default_get(
            'account.vat.prorata'))
    company_currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True, store=True,
        string='Company Currency')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ratio', 'Ratio'),
        ('done', 'Done'),
        ], string='State', index=True, readonly=True,
        track_visibility='onchange', default='draft', copy=False)

    _sql_constraints = [(
        'date_company_uniq',
        'unique(date_to, date_from, company_id)',
        'A pro rata VAT already exists in this company for the same dates!'
        )]

    def button_back2draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})
        self.delete_all_lines()
        if self.move_id:
            self.move_id.unlink()
        return True

    def delete_all_lines(self):
        avplo = self.env['account.vat.prorata.line']
        avpslo = self.env['account.vat.prorata.subject.line']
        lines = avplo.search([('parent_id', '=', self.id)])
        if lines:
            lines.unlink()
        subject_lines = avpslo.search([('parent_id', '=', self.id)])
        if subject_lines:
            subject_lines.unlink()

    def button_compute_ratio(self):
        self.ensure_one()
        avpslo = self.env['account.vat.prorata.subject.line']
        self.delete_all_lines()
        prec = self.company_id.currency_id.rounding
        target_move_sql = ' '
        if self.target_move == 'posted':
            target_move_sql = " AND am.state = 'posted' "
        request = """
            SELECT
                aml.account_id AS account_id,
                aa.vat_subject AS vat_subject,
                SUM(aml.debit) AS debit,
                SUM(aml.credit) AS credit,
                (SUM(aml.debit) - SUM(aml.credit)) AS balance
                FROM account_move_line aml
                LEFT JOIN account_move am ON aml.move_id = am.id
                LEFT JOIN account_account aa ON aa.id = aml.account_id
                WHERE aa.vat_subject in ('vat_subject', 'no_vat_subject')
                AND aml.company_id = %s
                AND am.date >= %s
                AND am.date <= %s
                AND am.journal_id in %s
            """ + target_move_sql + \
            """
                GROUP BY aml.account_id, aa.code, aa.vat_subject
                ORDER BY aa.code
            """
        self._cr.execute(
            request,
            (self.company_id.id, self.date_from, self.date_to,
             tuple(self.ratio_source_journal_ids.ids)))
        total = 0.0
        vat_subject_total = 0.0
        for row in self._cr.dictfetchall():
            # print "row=", row
            if (
                    float_is_zero(row['credit'], precision_rounding=prec) and
                    float_is_zero(row['debit'], precision_rounding=prec)):
                continue
            total += row['balance']
            if row['vat_subject'] == 'vat_subject':
                vat_subject_total += row['balance']
            vals = {
                'parent_id': self.id,
                'account_id': row['account_id'],
                'vat_subject': row['vat_subject'],
                'credit': row['credit'],
                'debit': row['debit'],
                'balance': row['balance'],
                }
            avpslo.create(vals)

        perct = 0.0
        if total:
            perct = 100 * vat_subject_total / total

        self.write({
            'state': 'ratio',
            'computed_perct': perct,
            'used_perct': perct,
            })

        return True

    def generate_prorata_lines(self):
        avplo = self.env['account.vat.prorata.line']
        amo = self.env['account.move']
        aao = self.env['account.account']
        ato = self.env['account.tax']
        company = self.company_id
        # delete existing prorata lines
        lines = avplo.search([('parent_id', '=', self.id)])
        if lines:
            lines.unlink()
        # Prepare datas
        ccur_prec = company.currency_id.rounding
        vat_deduc_accounts = aao.search([
            ('vat_deductible', '=', True), ('company_id', '=', company.id)])
        speed_acc2type = {}  # key = account_id, value = internal type
        accounts = aao.search_read(
            [('company_id', '=', company.id)], ['internal_type'])
        for acc in accounts:
            speed_acc2type[acc['id']] = acc['internal_type']
        speed_vattax2rate = {}
        vattaxes = ato.search([
            ('company_id', '=', company.id),
            ('type_tax_use', '=', 'purchase'),
            ('amount_type', '=', 'percent'),
            ('amount', '!=', False)])
        for vattax in vattaxes:
            if not float_is_zero(vattax.amount, precision_digits=4):
                speed_vattax2rate[vattax.id] = vattax.amount
        if not vat_deduc_accounts:
            raise UserError(_('No accounts are configured as VAT deductible'))
        ratio = (100.0 - self.used_perct) / 100.0
        # Get moves
        domain = [
            ('journal_id', 'in', self.source_journal_ids.ids),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('company_id', '=', company.id),
            ]
        if self.target_move == 'posted':
            domain.append(('state', '=', 'posted'))
        moves = amo.search(domain)
        work_moves = []
        for move in moves:
            tmp = {
                'vat': {},
                # key = line ID
                # value = {'bal': balance, 'prorata': balance * rate}
                'other_tax': {},
                # key = line ID
                # value = {'bal': balance, 'vat_rate': 5.5, 'weight': weight}
                'other_notax': {},
                # key = line ID
                # value = {'bal': balance, 'vat_rate': 100, 'weight': weight}
                'total_vat': 0.0,
                'total_weight_other_tax': 0.0,
                'total_weight_other_notax': 0.0}
            for line in move.line_ids:
                if float_is_zero(line.balance, precision_rounding=ccur_prec):
                    continue
                # VAT line
                if line.account_id in vat_deduc_accounts:
                    prorata_amt = float_round(
                        ratio * line.balance,
                        precision_rounding=ccur_prec)
                    tmp['vat'][line.id] = {
                        'bal': line.balance,
                        'prorata': prorata_amt}
                    tmp['total_vat'] += prorata_amt
                # Expense line with link to a VAT tax
                elif (
                        speed_acc2type[line.account_id.id] == 'other' and
                        line.tax_ids and
                        line.tax_ids[0].id in speed_vattax2rate):
                    vat_rate = speed_vattax2rate[line.tax_ids[0].id]
                    weight = vat_rate * line.balance
                    tmp['other_tax'][line.id] = {
                        'bal': line.balance,
                        'vat_rate': vat_rate,
                        'weight': weight}
                    tmp['total_weight_other_tax'] += weight
                # Expense line without link to a VAT tax
                elif speed_acc2type[line.account_id.id] == 'other':
                    vat_rate = 100
                    weight = vat_rate * line.balance
                    tmp['other_notax'][line.id] = {
                        'bal': line.balance,
                        'vat_rate': vat_rate,
                        'weight': weight,
                        }
                    tmp['total_weight_other_notax'] += weight
            if tmp['vat'] and not tmp['other_tax'] and not tmp['other_notax']:
                raise UserError(_(
                    "Move '%s' is very strange... shouldn't it be in another "
                    "journal than source journals ?"
                    " (debug: %s)") % (move.display_name, tmp))
            if tmp['vat']:
                work_moves.append(tmp)
        # Create lines
        for work_move in work_moves:
            if (
                    work_move['other_tax'] and
                    not float_is_zero(
                        work_move['total_weight_other_tax'],
                        precision_rounding=ccur_prec)):
                self.expense_prorata_line_create(work_move, 'other_tax')
            elif (
                    work_move['other_notax'] and
                    not float_is_zero(
                        work_move['total_weight_other_notax'],
                        precision_rounding=ccur_prec)):
                self.expense_prorata_line_create(work_move, 'other_notax')
            else:
                raise UserError(_(
                    'This scenario is not supported (debug: %s)') % work_move)
            for line_id, ldict in work_move['vat'].iteritems():
                avplo.create({
                    'parent_id': self.id,
                    'line_id': line_id,
                    'original_vat_amount': ldict['bal'],
                    'prorata_vat_amount': ldict['prorata'],
                    })
        return

    def expense_prorata_line_create(self, work_move, acc_type):
        avplo = self.env['account.vat.prorata.line']
        i = len(work_move[acc_type])
        vat_left = work_move['total_vat']
        for line_id, ldict in work_move[acc_type].iteritems():
            if i == 1:
                amt = vat_left
            else:
                amt = work_move['total_vat'] * ldict['weight'] /\
                    work_move['total_weight_' + acc_type]
            vat_left -= amt
            avplo.create({
                'parent_id': self.id,
                'line_id': line_id,
                'counterpart_amount': amt,
                'vat_rate': ldict['vat_rate'],
                'original_amount': ldict['bal'],
                })
            i -= 1

    def prepare_move(self):
        self.ensure_one()
        aao = self.env['account.account']
        company = self.company_id
        company_currency = company.currency_id
        prec = company_currency.rounding
        vat_deduc_accounts = aao.search([
            ('vat_deductible', '=', True), ('company_id', '=', company.id)])
        if not self.line_ids:
            raise UserError(_('There are no lines'))
        dlines = {}
        for line in self.line_ids:
            if line.account_id in vat_deduc_accounts:
                amt = line.prorata_vat_amount
            else:
                amt = - line.counterpart_amount

            if line.account_id in dlines:
                dlines[line.account_id] += amt
            else:
                dlines[line.account_id] = amt
        label = self.move_label
        lines = []
        prec_r = self.company_currency_id.rounding
        # for ordering by account code
        for account in aao.search([('company_id', '=', company.id)]):
            if account in dlines:
                lvals = {
                    'account_id': account.id,
                    'name': label,
                    }
                amount = float_round(
                    dlines[account], precision_rounding=prec_r)
                if float_compare(amount, 0, precision_rounding=prec) > 0:
                    lvals['credit'] = amount
                else:
                    lvals['debit'] = amount * -1
                lines.append((0, 0, lvals))
        vals = {
            'date': self.date_to,
            'journal_id': self.journal_id.id,
            'ref': label,
            'line_ids': lines,
            'company_id': company.id,
            }
        return vals

    def button_generate_move(self):
        self.ensure_one()
        self.generate_prorata_lines()
        move = self.env['account.move'].create(self.prepare_move())
        self.write({
            'state': 'done',
            'move_id': move.id,
            })
        action = self.env['ir.actions.act_window'].for_xml_id(
            'account', 'action_move_journal_line')
        action.update({
            'view_mode': 'form,tree',
            'res_id': move.id,
            'view_id': False,
            'views': False,
            })
        return action

    def name_get(self):
        res = []
        for rec in self:
            name = _('VAT Pro Rata %s -> %s') % (rec.date_from, rec.date_to)
            res.append((rec.id, name))
        return res

    def button_prorata_line_tree(self):
        action = self.env['ir.actions.act_window'].for_xml_id(
            'account_vat_pro_rata', 'account_vat_prorata_line_action')
        action.update({
            'domain': [('parent_id', '=', self.id)],
            'views': False,
            })
        return action


class AccountVatProrataSubjectLine(models.Model):
    _name = 'account.vat.prorata.subject.line'
    _description = 'Lines to compute VAT prorata ratio'

    parent_id = fields.Many2one(
        'account.vat.prorata', string='VAT Pro Rata', ondelete='cascade')
    company_currency_id = fields.Many2one(
        related='parent_id.company_currency_id',
        string="Company Currency", readonly=True)
    account_id = fields.Many2one(
        'account.account', string='Income Account', required=True)
    # vat_subject is NOT a related field because I need history
    vat_subject = fields.Selection([
        ('vat_subject', 'Income VAT Subject'),
        ('no_vat_subject', 'Income No VAT Subject'),
        ], string='VAT Subject')
    credit = fields.Monetary(currency_field='company_currency_id')
    debit = fields.Monetary(currency_field='company_currency_id')
    balance = fields.Monetary(
        string='Balance', currency_field='company_currency_id')


class AccountVatProrataLine(models.Model):
    _name = 'account.vat.prorata.line'
    _description = 'VAT Pro Rata calculation line'

    # TODO: maybe it's not a good idea to put related field
    parent_id = fields.Many2one(
        'account.vat.prorata', string='VAT Pro Rata', ondelete='cascade')
    company_currency_id = fields.Many2one(
        related='parent_id.company_currency_id',
        string="Company Currency", readonly=True)
    line_id = fields.Many2one(
        'account.move.line', string='Journal Items', readonly=True)
    date = fields.Date(related='line_id.date', readonly=True, store=True)
    move_id = fields.Many2one(
        related='line_id.move_id', readonly=True, store=True)
    account_id = fields.Many2one(
        related='line_id.account_id', readonly=True, store=True)
    partner_id = fields.Many2one(
        related='line_id.partner_id', readonly=True, store=True)
    label = fields.Char(
        related='line_id.name', readonly=True, store=True)
    original_vat_amount = fields.Monetary(
        string="VAT Amount", currency_field='company_currency_id')
    prorata_vat_amount = fields.Monetary(
        string="Pro Rata VAT Amount",
        currency_field='company_currency_id', readonly=True)
    counterpart_amount = fields.Monetary(
        string="Counter-part Amount",
        currency_field='company_currency_id')
    original_amount = fields.Monetary(
        string="Expense Amount",
        currency_field='company_currency_id')
    vat_rate = fields.Float(string='VAT Rate', digits=(16, 4))
