# Evaluation results

Model: `openai/gpt-oss-20b`, 22 tasks.

| Metric | Value |
|---|---|
| Task success rate | 100.0% |
| Correct tool selection | 100.0% |
| Average tool calls per task | 1.64 |
| Average LLM calls per task | 2.64 |
| Average time per task | 9.1 s |
| Tasks with a tool error | 1 (1 still answered correctly) |
| Tasks that hit the step limit | 0 |

## Per task

| Task | Success | Tools OK | Tools used |
|---|---|---|---|
| db_count | yes | yes | query_database |
| db_sum | yes | yes | query_database |
| db_group | yes | yes | query_database |
| db_filter | yes | yes | query_database |
| db_join | yes | yes | query_database |
| db_topn | yes | yes | query_database, query_database |
| order_lookup | yes | yes | get_order_status |
| order_missing | yes | yes | get_order_status, query_database |
| policy_express | yes | yes | search_policies |
| policy_warranty | yes | yes | search_policies |
| policy_restock | yes | yes | search_policies |
| policy_cancel | yes | yes | search_policies |
| policy_shipping_fee | yes | yes | search_policies |
| multi_refund | yes | yes | get_order_status, search_policies, calculate |
| multi_return_expired | yes | yes | get_order_status, search_policies |
| multi_loyalty_gold | yes | yes | search_policies, query_database |
| multi_loyalty_silver | yes | yes | search_policies, query_database |
| multi_delayed | yes | yes | get_order_status, search_policies |
| multi_address | yes | yes | get_order_status, search_policies |
| multi_calc | yes | yes | query_database, calculate |
| multi_percent | yes | yes | query_database, query_database, calculate |
| action_ticket | yes | yes | get_order_status, search_policies, create_ticket |
