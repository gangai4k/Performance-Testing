int log_order(char *order_id)
{
	char msg[256];

	if (strlen(order_id) == 0)
	{
		lr_error_message("Empty order id");
		return -1;
	}
	sprintf(msg, "Order %s created", order_id);
	lr_output_message("%s", msg);
	lr_save_string(order_id, "last_order");
	return 0;
}
