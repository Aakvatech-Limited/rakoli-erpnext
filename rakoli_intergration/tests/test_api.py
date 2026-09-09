import frappe
from frappe.tests import IntegrationTestCase

from rakoli_intergration.api import (
	check_loan_status,
	get_employee,
	record_loan,
	update_employee_bank,
	update_loan_status,
)
from rakoli_intergration.tests.utils import (
	create_employee,
	create_loan,
	create_loan_only_user,
	create_unprivileged_user,
)


class RakoliApiTestCase(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.response.pop("http_status_code", None)


class TestGetEmployee(RakoliApiTestCase):
	def test_missing_employee_number_returns_400(self):
		response = get_employee()
		self.assertEqual(response["error_code"], "MISSING_FIELD")
		self.assertEqual(frappe.local.response["http_status_code"], 400)

	def test_unknown_employee_returns_404(self):
		response = get_employee("NO-SUCH-EMPLOYEE")
		self.assertEqual(response["error_code"], "EMPLOYEE_NOT_FOUND")
		self.assertEqual(frappe.local.response["http_status_code"], 404)

	def test_inactive_employee_returns_422(self):
		employee = create_employee(status="Inactive", relieving_date=frappe.utils.nowdate())
		response = get_employee(employee.name)
		self.assertEqual(response["error_code"], "EMPLOYEE_NOT_ACTIVE")
		self.assertEqual(response["employment_status"], "Inactive")

	def test_active_employee_returns_payload(self):
		employee = create_employee()
		response = get_employee(employee.name)
		self.assertTrue(response["success"])
		data = response["data"]
		self.assertEqual(data["employee_number"], employee.name)
		self.assertEqual(data["bank_account_number"], "0000000000")
		self.assertEqual(data["employment_status"], "Active")

	def test_denied_for_user_without_employee_read_permission(self):
		employee = create_employee()
		user = create_unprivileged_user()
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			get_employee(employee.name)


class TestUpdateEmployeeBank(RakoliApiTestCase):
	def test_missing_fields_returns_400(self):
		response = update_employee_bank(employee_number="EMP-1")
		self.assertEqual(response["error_code"], "MISSING_FIELDS")

	def test_unknown_employee_returns_404(self):
		response = update_employee_bank("NO-SUCH-EMPLOYEE", "RMFB", "111")
		self.assertEqual(response["error_code"], "EMPLOYEE_NOT_FOUND")

	def test_inactive_employee_is_rejected(self):
		employee = create_employee(status="Left", relieving_date=frappe.utils.nowdate())
		response = update_employee_bank(employee.name, "RMFB", "111")
		self.assertEqual(response["error_code"], "EMPLOYEE_NOT_ACTIVE")

	def test_updates_bank_and_reports_previous_values(self):
		employee = create_employee()
		response = update_employee_bank(employee.name, "RMFB", "999888777")
		self.assertTrue(response["success"])
		data = response["data"]
		self.assertEqual(data["previous_bank_name"], "Old Bank")
		self.assertEqual(data["previous_bank_account_number"], "0000000000")
		self.assertEqual(
			frappe.db.get_value("Employee", employee.name, "bank_ac_no"),
			"999888777",
		)

	def test_denied_for_user_without_employee_write_permission(self):
		employee = create_employee()
		user = create_unprivileged_user()
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			update_employee_bank(employee.name, "Attacker Bank", "123123123")
		self.assertEqual(
			frappe.db.get_value("Employee", employee.name, "bank_ac_no"),
			"0000000000",
		)

	def test_denial_is_written_to_the_api_log(self):
		employee = create_employee()
		user = create_unprivileged_user()
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			get_employee(employee.name)
		frappe.set_user("Administrator")
		log = frappe.get_last_doc("Rakoli API Log", filters={"api_endpoint": "get_employee"})
		self.assertEqual(log.status_code, 403)
		self.assertIn("Not permitted", log.error_message)


class TestRecordLoan(RakoliApiTestCase):
	def test_missing_fields_returns_400(self):
		response = record_loan(employee_number="EMP-1")
		self.assertEqual(response["error_code"], "MISSING_FIELDS")

	def test_invalid_status_returns_422(self):
		employee = create_employee()
		response = record_loan(employee.name, 1000, loan_status="cancelled")
		self.assertEqual(response["error_code"], "INVALID_STATUS")

	def test_creates_loan_and_snapshots_bank_details(self):
		employee = create_employee()
		response = record_loan(employee.name, 750000, instalment_amount=75000, total_instalments=10)
		self.assertTrue(response["success"])
		loan = frappe.get_doc("Rakoli Loan", response["data"]["erpnext_loan_id"])
		self.assertEqual(loan.loan_amount, 750000)
		self.assertEqual(loan.loan_status, "received")
		self.assertEqual(loan.previous_bank_account, "0000000000")

	def test_many_loans_may_omit_the_external_id(self):
		employee = create_employee()
		first = record_loan(employee.name, 100000)
		second = record_loan(employee.name, 200000)
		self.assertNotEqual(first["data"]["erpnext_loan_id"], second["data"]["erpnext_loan_id"])
		self.assertEqual(frappe.db.count("Rakoli Loan", {"employee": employee.name}), 2)

	def test_replay_finds_a_loan_recorded_before_the_external_id_existed(self):
		employee = create_employee()
		legacy = create_loan(employee.name, loan_amount=100000)
		response = record_loan(employee.name, 400000, rakoli_loan_id=legacy.name)
		self.assertEqual(response["data"]["erpnext_loan_id"], legacy.name)
		self.assertEqual(frappe.db.count("Rakoli Loan", {"employee": employee.name}), 1)
		legacy.reload()
		self.assertEqual(legacy.loan_amount, 400000)

	def test_denied_for_user_who_cannot_read_employee_bank_details(self):
		employee = create_employee()
		user = create_loan_only_user()
		frappe.set_user(user.name)
		self.assertTrue(frappe.has_permission("Rakoli Loan", "create"))
		with self.assertRaises(frappe.PermissionError):
			record_loan(employee.name, 750000)

	def test_repeated_call_with_same_rakoli_loan_id_is_idempotent(self):
		employee = create_employee()
		first = record_loan(employee.name, 750000, rakoli_loan_id="RKL-EXT-001")
		second = record_loan(employee.name, 750000, rakoli_loan_id="RKL-EXT-001")
		self.assertEqual(
			first["data"]["erpnext_loan_id"],
			second["data"]["erpnext_loan_id"],
		)
		self.assertEqual(frappe.db.count("Rakoli Loan", {"employee": employee.name}), 1)

	def test_external_id_is_stored_and_echoed_back(self):
		employee = create_employee()
		response = record_loan(employee.name, 500000, rakoli_loan_id="RKL-EXT-777")
		self.assertEqual(response["data"]["rakoli_loan_id"], "RKL-EXT-777")
		self.assertNotEqual(response["data"]["erpnext_loan_id"], "RKL-EXT-777")
		self.assertEqual(
			frappe.db.get_value("Rakoli Loan", response["data"]["erpnext_loan_id"], "rakoli_loan_id"),
			"RKL-EXT-777",
		)

	def test_second_call_updates_the_existing_loan(self):
		employee = create_employee()
		record_loan(employee.name, 500000, rakoli_loan_id="RKL-EXT-778")
		second = record_loan(employee.name, 900000, rakoli_loan_id="RKL-EXT-778", loan_status="active")
		loan = frappe.get_doc("Rakoli Loan", second["data"]["erpnext_loan_id"])
		self.assertEqual(loan.loan_amount, 900000)
		self.assertEqual(loan.loan_status, "active")

	def test_denied_for_user_without_loan_create_permission(self):
		employee = create_employee()
		user = create_unprivileged_user()
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			record_loan(employee.name, 750000)


class TestCheckLoanStatus(RakoliApiTestCase):
	def test_missing_employee_number_returns_400(self):
		response = check_loan_status()
		self.assertEqual(response["error_code"], "MISSING_FIELD")

	def test_reports_no_active_loan(self):
		employee = create_employee()
		response = check_loan_status(employee.name)
		self.assertFalse(response["data"]["has_active_loan"])

	def test_reports_active_loan(self):
		employee = create_employee()
		loan = create_loan(employee.name, loan_status="active")
		response = check_loan_status(employee.name)
		data = response["data"]
		self.assertTrue(data["has_active_loan"])
		self.assertEqual(data["active_loans"][0]["erpnext_loan_id"], loan.name)

	def test_paid_loans_are_not_active(self):
		employee = create_employee()
		create_loan(employee.name, loan_status="paid")
		response = check_loan_status(employee.name)
		self.assertFalse(response["data"]["has_active_loan"])


class TestUpdateLoanStatus(RakoliApiTestCase):
	def test_missing_fields_returns_400(self):
		response = update_loan_status()
		self.assertEqual(response["error_code"], "MISSING_FIELDS")

	def test_invalid_status_returns_422(self):
		response = update_loan_status("RAK-LOAN-0001", "cancelled")
		self.assertEqual(response["error_code"], "INVALID_STATUS")

	def test_unknown_loan_returns_404(self):
		response = update_loan_status("NO-SUCH-LOAN", "active")
		self.assertEqual(response["error_code"], "LOAN_NOT_FOUND")

	def test_resolves_loan_by_external_rakoli_id(self):
		employee = create_employee()
		created = record_loan(employee.name, 500000, rakoli_loan_id="RKL-EXT-900")
		response = update_loan_status("RKL-EXT-900", "active")
		self.assertEqual(response["data"]["erpnext_loan_id"], created["data"]["erpnext_loan_id"])
		self.assertEqual(response["data"]["rakoli_loan_id"], "RKL-EXT-900")

	def test_transition_updates_status_and_adds_comment(self):
		employee = create_employee()
		loan = create_loan(employee.name)
		response = update_loan_status(loan.name, "approved", note="disbursed")
		self.assertEqual(response["data"]["previous_status"], "received")
		self.assertEqual(response["data"]["current_status"], "approved")

		loan.reload()
		self.assertEqual(loan.loan_status, "approved")
		self.assertTrue(loan.approved_at)

		comment = frappe.get_last_doc(
			"Comment",
			filters={"reference_doctype": "Rakoli Loan", "reference_name": loan.name},
		)
		self.assertIn("disbursed", comment.content)

	def test_denied_for_user_without_loan_write_permission(self):
		employee = create_employee()
		loan = create_loan(employee.name)
		user = create_unprivileged_user()
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			update_loan_status(loan.name, "paid")
