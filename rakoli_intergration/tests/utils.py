"""Fixture helpers shared by the Rakoli integration tests."""

import frappe
from frappe.utils import add_days, nowdate

TEST_COMPANY = "_Test Company"


def create_employee(**overrides) -> frappe.Document:
	"""Insert an Employee with Rakoli-relevant payroll and bank fields set."""
	values = {
		"doctype": "Employee",
		"first_name": "Rakoli",
		"last_name": "Tester",
		"gender": "Female",
		"date_of_birth": "1990-01-01",
		"date_of_joining": add_days(nowdate(), -365),
		"company": TEST_COMPANY,
		"status": "Active",
		"bank_name": "Old Bank",
		"bank_ac_no": "0000000000",
	}
	values.update(overrides)
	employee = frappe.get_doc(values)
	employee.insert(ignore_permissions=True)
	return employee


def create_loan(employee: str, **overrides) -> frappe.Document:
	"""Insert a Rakoli Loan for the given employee."""
	values = {
		"doctype": "Rakoli Loan",
		"employee": employee,
		"loan_amount": 500000,
		"loan_status": "received",
	}
	values.update(overrides)
	loan = frappe.get_doc(values)
	loan.insert(ignore_permissions=True)
	return loan


def create_unprivileged_user(email: str = "rakoli-outsider@example.com") -> frappe.Document:
	"""Insert an enabled User holding no roles beyond the implicit "All" role."""
	if frappe.db.exists("User", email):
		return frappe.get_doc("User", email)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Rakoli Outsider",
			"send_welcome_email": 0,
		}
	)
	user.insert(ignore_permissions=True)
	return user


def create_loan_only_user(email: str = "rakoli-loan-clerk@example.com") -> frappe.Document:
	"""Inserts a User who may create and write Rakoli Loan but cannot read Employee."""
	role = "Rakoli Loan Clerk"
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if not frappe.db.exists("Custom DocPerm", {"parent": "Rakoli Loan", "role": role}):
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Rakoli Loan",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"read": 1,
				"write": 1,
				"create": 1,
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(doctype="Rakoli Loan")

	if frappe.db.exists("User", email):
		return frappe.get_doc("User", email)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Rakoli Clerk",
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	)
	user.insert(ignore_permissions=True)
	return user
