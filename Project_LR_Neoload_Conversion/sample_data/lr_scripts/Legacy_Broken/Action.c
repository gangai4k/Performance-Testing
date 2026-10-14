Action()
{
	lr_start_transaction("LG_01_Portal");

	web_url("portal",
		"URL=http://legacy.example.local:8080/portal",
		"Mode=HTML",
		LAST);

	/* The closing brace of this block is missing on purpose: the converter
	   must report FAILED for this script instead of crashing the batch. */
	if (1)
	{
		lr_rendezvous("peak");

	return 0;
}
