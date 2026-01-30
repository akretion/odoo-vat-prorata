# Copyright 2017-2022 Akretion (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models, api, _
from odoo.fields import Command
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
        res.update({
            'company_id': company.id,
            'date_from': date_from_dt,
            'date_to': date_to_dt,
            'journal_id': jl_id,
            'source_journal_ids': [Command.set(source_jrls.ids)],
            'move_label': _('VAT Pro Rata'),
        })
        return res

    date_from = fields.Date(
        string="Date From",
        required=True,
        tracking=True)
    date_to = fields.Date(
        string="Date To",
        required=True,
        copy=False, tracking=True)
    target_move = fields.Selection([
        ('posted', 'All Posted Entries'),
        ('all', 'All Entries')],
        string='Target Moves', required=True, default='all',
        tracking=True)
    source_journal_ids = fields.Many2many(
        'account.journal', string='Source Journals', required=True,
        domain="[('company_id', '=', company_id)]")
    journal_id = fields.Many2one(
        'account.journal', string='VAT Pro Rata Journal', required=True,
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
        check_company=True)
    move_id = fields.Many2one(
        'account.move', string='VAT Pro Rata Entry', readonly=True,
        copy=False, check_company=True)
    move_label = fields.Char(
        string='Label of the VAT Pro Rata Entry', required=True,
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
        string='VAT Subject Used Ratio',
        digits='VAT Pro Rata Ratio', tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
    )
    company_currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, string='Company Currency')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ratio', 'Ratio'),
        ('done', 'Done'),
        ], string='State', index=True, readonly=True,
        tracking=True, default='draft', copy=False)
    warning_reversal = fields.Char(compute="_compute_warning_reversal")

    _sql_constraints = [(
        'date_company_uniq',
        'unique(date_to, date_from, company_id)',
        'A pro rata VAT already exists in this company for the same dates!'
        )]

    def _get_previous_prorata_domain(self):
        self.ensure_one()
        return [
            ('date_to', '<', self.date_to),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'done')
        ]

    def _get_previous_prorata(self):
        self.ensure_one()
        domain = self._get_previous_prorata_domain()
        return self.search(domain, order="date_to desc", limit=1)

    def _compute_warning_reversal(self):
        for rec in self:
            last = rec._get_previous_prorata()

            # reversal is needed for all month but the last of the fiscalyear.
            # so the first month, no need to check (because we check last month)
            if rec.date_from.month == rec.date_to.month or not last:
                rec.warning_reversal = False
                continue
            if not last.move_id.reversal_move_ids.filtered(lambda m: m.state == "posted"):
                rec.warning_reversal = self.env._(
                    "Missing Reversal! The previous calculation (%s) "
                    "has not been reversed, or the reversal has not been validated"
                ) % (last.display_name,)
            else:
                rec.warning_reversal = False

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
        if self.target_move == 'posted':
            target_move_sql = " AND am.state = 'posted' "
        else:
            target_move_sql = " AND am.state in ('draft', 'posted') "

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
            """ + target_move_sql + \
            """
                GROUP BY aml.account_id, aa.code_store->>%s, aa.vat_subject
                ORDER BY aa.code_store->>%s
            """
        self._cr.execute(
            request,
            (self.company_id.id, self.date_from, self.date_to, self.company_id.id, self.company_id.id)
            )
        total = 0.0
        vat_subject_total = 0.0
        for row in self._cr.dictfetchall():
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
            ])
        for tax in deduc_vat_taxes:
            line = tax.invoice_repartition_line_ids.filtered(
                lambda x: x.repartition_type == "tax"
                and x.account_id.account_type not in ("expense", "expense_depreciation", "expense_direct_cost")
                and int(x.factor_percent) > 0 
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
            [('company_ids', 'in', [company.id])], ['account_type'])
        for acc in accounts:
            speed_acc2type[acc['id']] = acc['account_type']
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
            # I decided NOT to filter on 'fiscal_position_fr_vat_type' even if it can improve
            # a little bit the perfs, because it is technically possible to have
            # French VAT taxes on invoice line with a fiscal position not in
            # france/france_vendor_vat_on_payment/False if the user has manually
            # set the taxes on the invoice line.
            # ('fiscal_position_fr_vat_type', 'in', ('france', 'france_vendor_vat_on_payment', False)),
            ]
        if self.target_move == 'posted':
            domain.append(('state', '=', 'posted'))
        else:
            domain.append(('state', 'in', ('draft', 'posted')))
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
                        # what about account.asset, take this type into account ?
                        speed_acc2type[line.account_id.id] in ("expense", "expense_depreciation", "expense_direct_cost") and
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
                elif speed_acc2type[line.account_id.id] in ("expense", "expense_depreciation", "expense_direct_cost"):
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
                "analytic_distribution": self.env["account.move.line"].browse(line_id).analytic_distribution,
                })
            i -= 1

    def _get_consolidated_analytic_distribution(self, lines):
        total_amount = sum(lines.mapped('counterpart_amount'))
        if self.company_id.currency_id.is_zero(total_amount):
            return {}
    
        distribution_by_plan = {}

        # get sum by plan and analytic account
        for line in lines:
            if not line.analytic_distribution:
                continue
    
            for analytic_id, percentage in line.analytic_distribution.items():
                analytic_account = self.env["account.analytic.account"].browse(int(analytic_id))
                plan = analytic_account.plan_id
    
                if plan.id not in distribution_by_plan:
                    distribution_by_plan[plan.id] = {}
    
                share = line.counterpart_amount * (percentage / 100.0)
                distribution_by_plan[plan.id][analytic_account.id] = \
                    distribution_by_plan[plan.id].get(analytic_account.id, 0.0) + share
    
        # Convert to amounts to ratio
        final_distribution = {}
        for plan_id, analytics in distribution_by_plan.items():
            plan_dist = {}
            for analytic_id, total_share in analytics.items():
                plan_dist[analytic_id] = round((total_share / total_amount) * 100.0, 2)
    
            # Manage rounding issues : If the sum of the rato is really near 100%
            # we consider it is a rounding issue and we round it to 100%
            # else we consider that maybe the plan is optional and we keep the partial
            # percentage. Hard to manage all cases otherwise (mandatory plan  /
            # mandatory only on some case, became mandatory in the middle of the month
            current_sum = sum(plan_dist.values())
            if current_sum > 99.9 and current_sum < 100.1:
                # get the key that have the bigget value
                max_key = max(plan_dist, key=plan_dist.get)
                plan_dist[max_key] = round(plan_dist[max_key] + (100.0 - current_sum), 2)
    
            # On fusionne dans le dictionnaire final
            final_distribution.update(plan_dist)
    
        return final_distribution

    def prepare_move(self):
        self.ensure_one()
        company = self.company_id
        ccur = company.currency_id
        if not self.line_ids:
            raise UserError(_('There are no lines'))
        grouped_lines = defaultdict(lambda: self.env['account.vat.prorata.line'])
        for line in self.line_ids:
            if ccur.is_zero(line.prorata_vat_amount) and ccur.is_zero(line.counterpart_amount):
                continue

            key = (
                line.account_id,
                line.start_date or False,
                line.end_date or False
            )
            grouped_lines[key] |= line
        lines = []
        # Needed to neutralise default asset profile that may be
        # configured on asset account and that will block
        # account move posting
        asset_installed = False
        if hasattr(self.env['account.account'], 'asset_profile_id'):
            asset_installed = True
        # for ordering by account code
        for key, prorata_lines in grouped_lines.items():
            account, start_date, end_date = key
            amount = sum(
                line.prorata_vat_amount if not ccur.is_zero(line.prorata_vat_amount) else -line.counterpart_amount 
                for line in prorata_lines
            )
            amount = ccur.round(amount)
            lvals = {
                'start_date': start_date,
                'end_date': end_date,
                'account_id': account.id,
                'account_code': account.code,  # for sorting
                }
            if account.account_type in ('expense', 'expense_depreciation', 'expense_direct_cost'):
                lvals['analytic_distribution'] = self._get_consolidated_analytic_distribution(prorata_lines)

            if asset_installed:
                lvals['asset_profile_id'] = False
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

    def _compute_display_name(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.display_name = self.env._('VAT Pro Rata %s -> %s') % (
                    format_date(self.env, rec.date_from),
                    format_date(self.env, rec.date_to)
                )
            else:
                rec.display_name = self.env._('New VAT Pro Rata')

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
    company_id = fields.Many2one(related="parent_id.company_id")
    analytic_distribution = fields.Json(readonly=True)
    # we do not really need the mixing so we add this field here
    analytic_precision = fields.Integer(
        store=False,
        default=lambda self: self.env['decimal.precision'].precision_get("Percentage Analytic"),
    )

