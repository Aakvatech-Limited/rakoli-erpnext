import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from rakoli_intergration.tests.utils import TEST_COMPANY, create_employee
from rakoli_intergration.utils import (
	get_salary_data,
	log_api_call,
	make_error_response,
	make_success_response,
)


class TestResponseHelpers(IntegrationTestCase):
	def test_success_response_shape(self):
		response = make_success_response({"employee_number": "EMP-1"})
		self.assertTrue(response["success"])
		self.assertEqual(response["data"], {"employee_number": "EMP-1"})
		self.assertIn("timestamp", response)

	def test_error_response_sets_http_status_code(self):
		response = make_error_response(404, "EMPLOYEE_NOT_FOUND", "missing")
		self.assertFalse(response["success"])
		self.assertEqual(response["error_code"], "EMPLOYEE_NOT_FOUND")
		self.assertEqual(frappe.local.response["http_status_code"], 404)
		self.assertNotIn("field", response)

	def test_error_response_includes_field_when_given(self):
		response = make_error_response(400, "MISSING_FIELD", "required", "employee_number")
		self.assertEqual(response["field"], "employee_number")


class TestSalaryData(IntegrationTestCase):
	def test_returns_none_when_no_payroll_records(self):
		employee = create_employee()
		self.assertEqual(get_salary_data(employee.name), (None, None))

	def test_falls_back_to_salary_structure_assignment_base(self):
		employee = create_employee()
		frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": employee.name,
				"company": TEST_COMPANY,
				"from_date": add_days(nowdate(), -30),
				"base": 1200000,
				"docstatus": 1,
			}
		).db_insert()

		gross, net = get_salary_data(employee.name)
		self.assertEqual(gross, 1200000)
		self.assertIsNone(net)


class TestApiLogging(IntegrationTestCase):
	def test_log_api_call_records_request_and_response(self):
		employee = create_employee()
		log_api_call(
			"get_employee",
			"GET",
			{"employee_number": employee.name},
			{"success": True},
			200,
			employee=employee.name,
		)
		log = frappe.get_last_doc("Rakoli API Log", filters={"api_endpoint": "get_employee"})
		self.assertEqual(log.status_code, 200)
		self.assertEqual(log.employee, employee.name)
		self.assertIn(employee.name, log.request_data)

	def test_log_api_call_drops_unknown_links(self):
		log_api_call("get_employee", "GET", None, None, 404, employee="NO-SUCH-EMPLOYEE")
		log = frappe.get_last_doc("Rakoli API Log", filters={"status_code": 404})
		self.assertIsNone(log.employee)
