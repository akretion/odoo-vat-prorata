# -*- coding: utf-8 -*-
# © 2017 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'VAT Pro Rata',
    'version': '10.0.1.0.0',
    'category': 'Accounting & Finance',
    'license': 'AGPL-3',
    'summary': 'Manages VAT Pro Rata',
    'description': """
VAT Pro Rata
============

This module helps to manage VAT Pro Rata. Specifications for the implementation in Odoo are available here in French: https://docs.google.com/document/d/13SKJutICHL5JFNXWaB1pDXvafG0c_W8qSly5uGz1--w/edit?usp=sharing

To know more about the rules of VAT Pro Rata in France, read this: http://circulaire.legifrance.gouv.fr/pdf/2012/01/cir_34487.pdf This Odoo module implements VAT Pro Rata with *clé de répartition unique*, as explained in section 1.2.4 of the instruction n° 12-002-M0 of January 19th 2012.

This module has been written by Alexis de Lattre from Akretion
<alexis.delattre@akretion.com>.
    """,
    'author': 'Akretion',
    'website': 'http://www.akretion.com',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'security/rule.xml',
        'data/decimal_precision_data.xml',
        'views/account_account.xml',
        'views/account_config_settings.xml',
        'views/account_vat_prorata.xml',
    ],
    'installable': True,
    'application': True,
}
