# Copyright 2017-2022 Akretion (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models, api, _
from odoo.tools import float_is_zero, float_round
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
from odoo.tools.misc import format_date
from collections import defaultdict
import logging
logger = logging.getLogger(__name__)


class AccountVatProrata(models.Model):
    _name = 'account.vat.prorata'
    _description = 'VAT Pro Rata calculation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc'
    _check_company_auto = True

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today_dt = fields.Date.context_today(self)
        date_from_dt = today_dt + relativedelta(months=-1) +\
            relativedelta(month=1, day=1)
        date_to_dt = today_dt + relativedelta(day=1) + relativedelta(days=-1)
        company = self.env.company
        jl_id = company.vat_prorata_journal_id.id or False
        source_jrls = self.env['account.journal'].search([
            ('type', '=', 'purchase'), ('company_id', '=', company.id)])
        ratio_source_jrls = self.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', company.id)])
        res.update({
            'company_id': company.id,
            'date_from': date_from_dt,
            'date_to': date_to_dt,
            'journal_id': jl_id,
            'source_journal_ids': source_jrls.ids,
            'ratio_source_journal_ids': ratio_source_jrls.ids,
            'move_label': _('VAT Pro Rata'),
        })
        return res

    date_from = fields.Date(
        string="Date From",
        required=True, readonly=True, states={'draft': [('readonly', False)]},
        tracking=True)
    date_to = fields.Date(
        string="Date To",
        required=True, readonly=True, states={'draft': [('readonly', False)]},
        copy=False, tracking=True)
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
        tracking=True)
    source_journal_ids = fields.Many2many(
        'account.journal', string='Source Journals', readonly=True,
        states={'draft': [('readonly', False)]}, required=True,
        domain="[('company_id', '=', company_id)]")
    journal_id = fields.Many2one(
        'account.journal', string='VAT Pro Rata Journal', required=True,
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
        states={'done': [('readonly', True)]}, check_company=True)
    move_id = fields.Many2one(
        'account.move', string='VAT Pro Rata Entry', readonly=True,
        copy=False, check_company=True)
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
        digits='VAT Pro Rata Ratio', tracking=True)
    used_perct = fields.Float(
        string='VAT Subject Used Ratio', states={'done': [('readonly', True)]},
        digits='VAT Pro Rata Ratio', tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        states={'done': [('readonly', True)]})
    company_currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, string='Company Currency')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ratio', 'Ratio'),
        ('done', 'Done'),
        ], string='State', index=True, readonly=True,
        tracking=True, default='draft', copy=False)

    _sql_constraints = [(
        'date_company_uniq',
        'unique(date_to, date_from, company_id)',
        'A pro rata VAT already exists in this company for the same dates!'
        )]

    @api.constrains('date_from', 'date_to')
    def _check_vat_prorata(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from >= rec.date_to:
                raise ValidationError(_(
                    "Date To ({date_to}) must be after Date From ({date_from})."
                    ).format(
                        date_to=format_date(self.env, rec.date_to),
                        date_from=format_date(self.env, rec.date_from)))

    def button_back2draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})
        self.delete_all_lines()
        if self.move_id:
            self.move_id.unlink()

    def delete_all_lines(self):
        self.ensure_one()
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
        if not self.company_id.vat_prorata:
            raise UserError(_(
                "Company '%s' doesn't have VAT Prorata.")
                % self.company_id.display_name)
        self.delete_all_lines()
        ccur = self.company_id.currency_id
        target_move_sql = ' '
        if self.target_move == 'posted':
            target_move_sql = " AND am.state = 'posted' "
        request = """
            SELECT
                aml.account_id AS account_id,
                aa.vat_subject AS vat_subject,
                SUM(aml.debit) AS debit,
                SUM(aml.credit) AS credit,
                SUM(aml.balance) AS balance
                FROM account_move_line aml
                LEFT JOIN account_move am ON aml.move_id = am.id
                LEFT JOIN account_account aa ON aa.id = aml.account_id
                WHERE aa.vat_subject in ('vat_subject', 'no_vat_subject')
                AND am.company_id = %s
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
            if ccur.is_zero(row['credit']) and ccur.is_zero(row['debit']):
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
        perct_prec = self.env['decimal.precision'].precision_get(
            'VAT Pro Rata Ratio')
        if total:
            perct = float_round(
                100 * vat_subject_total / total, precision_digits=perct_prec)

        self.write({
            'state': 'ratio',
            'computed_perct': perct,
            'used_perct': perct,
            })

    def _get_vat_deduc_accounts(self):
        vat_deduc_accounts = self.env['account.account']
        deduc_vat_taxes = self.env['account.tax'].search([
            ('company_id', '=', self.company_id.id),
            ("amount_type", "=", "percent"),
            ("amount", ">", 0),
            ("type_tax_use", "=", "purchase"),
            ("fr_vat_autoliquidation", "=", False),
            ])
        for tax in deduc_vat_taxes:
            line = tax.invoice_repartition_line_ids.filtered(
                lambda x: x.repartition_type == "tax"
                and x.account_id
                and int(x.factor_percent) == 100
            )
            if len(line) != 1:
                raise UserError(
                    _("Bad configuration on regular purchase tax %s.")
                    % tax.display_name
                )
            vat_account = line.account_id
            vat_account_code = vat_account.code
            if (
                    not vat_account_code.startswith('44562') and
                    not vat_account_code.startswith('44566')):
                raise UserError(_(
                    "Tax {tax} has been considered as a deductible VAT tax, "
                    "but it's not true because it's account code is "
                    "'{account_code}'.").format(
                        tax=tax.display_name,
                        account_code=vat_account_code))
            vat_deduc_accounts |= vat_account
        if not vat_deduc_accounts:
            raise UserError(_('No accounts are configured as VAT deductible'))
        logger.debug('vat_deduc_accounts=%s', [acc.code for acc in vat_deduc_accounts])
        return vat_deduc_accounts

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
        ccur = company.currency_id

        vat_deduc_accounts = self._get_vat_deduc_accounts()
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
            ('amount', '>', 0)])
        for vattax in vattaxes:
            if not float_is_zero(vattax.amount, precision_digits=4):
                speed_vattax2rate[vattax.id] = vattax.amount
        ratio = (100.0 - self.used_perct) / 100.0
        # Get moves
        domain = [
            ('journal_id', 'in', self.source_journal_ids.ids),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('company_id', '=', company.id),
            ('fiscal_position_fr_vat_type', 'in', ('france', False)),
            ]
        if self.target_move == 'posted':
            domain.append(('state', '=', 'posted'))
        moves = amo.search(domain)
        work_moves = []
        for move in moves:
            tmp = {
                'vat': {},
                # key = line ID
                # value = {'bal': balance, 'prorata': balance * ratio}
                'other_tax': {},
                # key = line ID
                # value = {'bal': balance, 'vat_rate': 5.5, 'weight': weight}
                'other_notax': {},
                # key = line ID
                # value = {'bal': balance, 'vat_rate': 100, 'weight': weight}
                'total_vat': 0.0,
                'total_weight_other_tax': 0.0,
                'total_weight_other_notax': 0.0}
            # in v14, 'other_notax' is almost not used because we always encode
            # a purchase moves via invoice lines in common scenarios
            for line in move.line_ids:
                if ccur.is_zero(line.balance):
                    continue
                # VAT line
                if line.account_id in vat_deduc_accounts:
                    prorata_amt = ccur.round(ratio * line.balance)
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
                from pprint import pprint
                print('move=', move.name)
                pprint(tmp)
                work_moves.append(tmp)
        # Create lines
        for work_move in work_moves:
            if (
                    work_move['other_tax'] and
                    not ccur.is_zero(work_move['total_weight_other_tax'])):
                self.expense_prorata_line_create(work_move, 'other_tax', ccur)
            elif (
                    work_move['other_notax'] and
                    not ccur.is_zero(work_move['total_weight_other_notax'])):
                self.expense_prorata_line_create(
                    work_move, 'other_notax', ccur)
            else:
                raise UserError(_(
                    'This scenario is not supported (debug: %s)') % work_move)
            for line_id, ldict in work_move['vat'].items():
                avplo.create({
                    'parent_id': self.id,
                    'line_id': line_id,
                    'original_vat_amount': ldict['bal'],
                    'prorata_vat_amount': ldict['prorata'],
                    })
        return

    def expense_prorata_line_create(self, work_move, acc_type, ccur):
        avplo = self.env['account.vat.prorata.line']
        i = len(work_move[acc_type])
        vat_left = work_move['total_vat']  # already rounded
        for line_id, ldict in work_move[acc_type].items():
            if i == 1:
                amt = ccur.round(vat_left)  # rounding "optional" here
            else:
                amt = ccur.round(
                    work_move['total_vat'] * ldict['weight'] /
                    work_move['total_weight_' + acc_type])
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
        company = self.company_id
        ccur = company.currency_id
        if not self.line_ids:
            raise UserError(_('There are no lines'))
        dlines = defaultdict(float)
        for line in self.line_ids:
            if not ccur.is_zero(line.prorata_vat_amount):
                amt = line.prorata_vat_amount
            elif not ccur.is_zero(line.counterpart_amount):
                amt = - line.counterpart_amount
            else:
                continue

            key = (
                line.account_id,
                line.start_date or False,
                line.end_date or False)
            dlines[key] += amt
        lines = []
        # for ordering by account code
        for (key, amount) in dlines.items():
            account, start_date, end_date = key
            lvals = {
                'start_date': start_date,
                'end_date': end_date,
                'account_id': account.id,
                'account_code': account.code,  # for sorting
                }
            amount = ccur.round(amount)
            if ccur.compare_amounts(amount, 0) > 0:
                lvals['credit'] = amount
            else:
                lvals['debit'] = amount * -1
            lines.append(lvals)

        # Order by account code
        ordered_lines = sorted(lines, key=lambda x: x['account_code'])
        vals = {
            'date': self.date_to,
            'journal_id': self.journal_id.id,
            'ref': self.move_label,
            'line_ids': [x.pop('account_code') and (0, 0, x) for x in ordered_lines],
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
        # I think it's better to stay on the VAT prorata form view
#        action = self.env['ir.actions.actions']._for_xml_id(
#            'account.action_move_journal_line')
#        action.update({
#            'view_mode': 'form,tree',
#            'res_id': move.id,
#            'view_id': False,
#            'views': False,
#            })
#        return action

    def name_get(self):
        res = []
        for rec in self:
            name = _('VAT Pro Rata %s -> %s') % (rec.date_from, rec.date_to)
            res.append((rec.id, name))
        return res

    def button_prorata_line_tree(self):
        action = self.env['ir.actions.actions']._for_xml_id(
            'account_vat_pro_rata.account_vat_prorata_line_action')
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
        string="Company Currency")
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

    parent_id = fields.Many2one(
        'account.vat.prorata', string='VAT Pro Rata', ondelete='cascade')
    company_currency_id = fields.Many2one(
        related='parent_id.company_currency_id', string="Company Currency")
    line_id = fields.Many2one(
        'account.move.line', string='Journal Items', readonly=True)
    date = fields.Date(related='line_id.date', store=True)
    move_id = fields.Many2one(
        related='line_id.move_id', store=True)
    account_id = fields.Many2one(
        related='line_id.account_id', store=True)
    partner_id = fields.Many2one(
        related='line_id.partner_id', store=True)
    ref = fields.Char(related='line_id.ref', store=True)
    label = fields.Char(
        related='line_id.name', store=True)
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
    start_date = fields.Date(
        related='line_id.start_date', store=True)
    end_date = fields.Date(
        related='line_id.end_date', store=True)
