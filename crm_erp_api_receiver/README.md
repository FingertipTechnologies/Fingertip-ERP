# ERP CRM/PMS Integration — Odoo 19 (Change 3 revised)

- Incoming CRM/PMS `/api/v1/customers/upsert` remains unchanged (Changes 1 and 2).
- ERP scheduled action `ERP Existing Customer Codes to CRM/PMS` generates missing customer codes on ERP company records and sends only `name`, `website`, `customer_code`, `erp_customer_id` to CRM/PMS.
- ERP receiver URL: `http://127.0.0.1:8019/api/v1/erp/customer-code/sync` (replace port where applicable).
- CRM/PMS does **not** create new customers or contacts through this scheduled action.
- ERP sync states: pending, success, not_found, failed. Pending processed first; failed/not_found retried hourly. Success records skipped.
- Configure outbound URL and receiver Bearer token under Settings.
