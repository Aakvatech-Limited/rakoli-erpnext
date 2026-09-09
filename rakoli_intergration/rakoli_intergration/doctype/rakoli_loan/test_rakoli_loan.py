import frappe
from frappe.tests import IntegrationTestCase

from rakoli_intergration.tests.utils import create_employee


class TestRakoliLoan(IntegrationTestCase):
	def test_employee_and_loan_amount_are_mandatory(self):
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({"doctype": "Rakoli Loan"}).insert(ignore_permissions=True)

	def test_autoname_uses_rakoli_loan_series(self):
		employee = create_employee()
		loan = frappe.get_doc(
			{
				"doctype": "Rakoli Loan",
				"employee": employee.name,
				"loan_amount": 250000,
			}
		)
		loan.insert(ignore_permissions=True)
		self.assertTrue(loan.name.startswith("RAK-LOAN-"))

	def test_rejects_status_outside_the_select_options(self):
		employee = create_employee()
		loan = frappe.get_doc(
			{
				"doctype": "Rakoli Loan",
				"employee": employee.name,
				"loan_amount": 250000,
				"loan_status": "cancelled",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			loan.insert(ignore_permissions=True)
