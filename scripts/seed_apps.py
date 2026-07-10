#!/usr/bin/env python3
"""
scripts/seed_apps.py
--------------------
Generate a sample apps.csv with 100 real SaaS applications.
Run: python scripts/seed_apps.py
"""

from __future__ import annotations

import csv
from pathlib import Path

APPS = [
    # Payments & Finance
    ("Stripe", "https://stripe.com", "Payments"),
    ("Braintree", "https://developer.paypal.com/braintree", "Payments"),
    ("Square", "https://developer.squareup.com", "Payments"),
    ("Plaid", "https://plaid.com", "Fintech"),
    ("Adyen", "https://www.adyen.com/developers", "Payments"),
    ("Paddle", "https://developer.paddle.com", "Payments"),
    ("Chargebee", "https://apidocs.chargebee.com", "Billing"),
    ("Recurly", "https://developers.recurly.com", "Billing"),
    ("Zuora", "https://developer.zuora.com", "Billing"),
    ("QuickBooks", "https://developer.intuit.com", "Accounting"),

    # Communications
    ("Twilio", "https://www.twilio.com/docs", "Communications"),
    ("SendGrid", "https://docs.sendgrid.com", "Email"),
    ("Mailgun", "https://documentation.mailgun.com", "Email"),
    ("Postmark", "https://postmarkapp.com/developer", "Email"),
    ("Vonage", "https://developer.vonage.com", "Communications"),
    ("MessageBird", "https://developers.messagebird.com", "Communications"),
    ("Bandwidth", "https://dev.bandwidth.com", "Communications"),
    ("Sinch", "https://developers.sinch.com", "Communications"),
    ("Mailchimp", "https://mailchimp.com/developer", "Email Marketing"),
    ("Klaviyo", "https://developers.klaviyo.com", "Email Marketing"),

    # Developer Tools
    ("GitHub", "https://docs.github.com/en/rest", "Developer Tools"),
    ("GitLab", "https://docs.gitlab.com/ee/api", "Developer Tools"),
    ("Jira", "https://developer.atlassian.com/cloud/jira", "Project Management"),
    ("Linear", "https://developers.linear.app", "Project Management"),
    ("PagerDuty", "https://developer.pagerduty.com", "Incident Management"),
    ("Datadog", "https://docs.datadoghq.com/api", "Monitoring"),
    ("New Relic", "https://docs.newrelic.com/docs/apis", "Monitoring"),
    ("Sentry", "https://docs.sentry.io/api", "Error Tracking"),
    ("LaunchDarkly", "https://apidocs.launchdarkly.com", "Feature Flags"),
    ("Vercel", "https://vercel.com/docs/rest-api", "Deployment"),

    # CRM & Sales
    ("Salesforce", "https://developer.salesforce.com", "CRM"),
    ("HubSpot", "https://developers.hubspot.com", "CRM"),
    ("Pipedrive", "https://developers.pipedrive.com", "CRM"),
    ("Zoho CRM", "https://www.zoho.com/crm/developer", "CRM"),
    ("Close", "https://developer.close.com", "CRM"),
    ("Copper", "https://developer.copper.com", "CRM"),
    ("Freshsales", "https://developers.freshworks.com/crm", "CRM"),
    ("ActiveCampaign", "https://developers.activecampaign.com", "Marketing Automation"),
    ("Intercom", "https://developers.intercom.com", "Customer Support"),
    ("Zendesk", "https://developer.zendesk.com", "Customer Support"),

    # Productivity & Collaboration
    ("Slack", "https://api.slack.com", "Collaboration"),
    ("Microsoft Teams", "https://learn.microsoft.com/en-us/graph", "Collaboration"),
    ("Notion", "https://developers.notion.com", "Productivity"),
    ("Airtable", "https://airtable.com/developers/web/api", "Productivity"),
    ("Asana", "https://developers.asana.com", "Project Management"),
    ("Monday.com", "https://developer.monday.com", "Project Management"),
    ("ClickUp", "https://clickup.com/api", "Project Management"),
    ("Trello", "https://developer.atlassian.com/cloud/trello", "Project Management"),
    ("Basecamp", "https://github.com/basecamp/bc3-api", "Project Management"),
    ("Todoist", "https://developer.todoist.com", "Productivity"),

    # E-commerce & Retail
    ("Shopify", "https://shopify.dev/docs/api", "E-commerce"),
    ("WooCommerce", "https://woocommerce.github.io/woocommerce-rest-api-docs", "E-commerce"),
    ("BigCommerce", "https://developer.bigcommerce.com", "E-commerce"),
    ("Magento", "https://developer.adobe.com/commerce", "E-commerce"),
    ("Klaviyo", "https://developers.klaviyo.com", "E-commerce Marketing"),
    ("Shippo", "https://docs.goshippo.com/docs", "Shipping"),
    ("EasyPost", "https://www.easypost.com/docs/api", "Shipping"),
    ("ShipStation", "https://www.shipstation.com/docs/api", "Shipping"),
    ("Avalara", "https://developer.avalara.com", "Tax"),
    ("TaxJar", "https://developers.taxjar.com", "Tax"),

    # Cloud Infrastructure
    ("AWS", "https://docs.aws.amazon.com/index.html", "Cloud"),
    ("Google Cloud", "https://cloud.google.com/apis/docs/overview", "Cloud"),
    ("Azure", "https://learn.microsoft.com/en-us/rest/api/azure", "Cloud"),
    ("DigitalOcean", "https://docs.digitalocean.com/reference/api", "Cloud"),
    ("Cloudflare", "https://developers.cloudflare.com", "Cloud"),
    ("Supabase", "https://supabase.com/docs/reference/api", "Backend"),
    ("Firebase", "https://firebase.google.com/docs/reference/rest", "Backend"),
    ("Neon", "https://api-docs.neon.tech", "Database"),
    ("PlanetScale", "https://planetscale.com/docs/concepts/planetscale-api-guide", "Database"),
    ("MongoDB Atlas", "https://www.mongodb.com/docs/atlas/api", "Database"),

    # Analytics & Data
    ("Segment", "https://segment.com/docs/connections/sources/catalog/libraries/server/http-api", "Analytics"),
    ("Mixpanel", "https://developer.mixpanel.com", "Analytics"),
    ("Amplitude", "https://www.docs.developers.amplitude.com", "Analytics"),
    ("Heap", "https://help.heap.io/data-management/server-side-apis", "Analytics"),
    ("Looker", "https://developers.looker.com/api/explorer", "Business Intelligence"),
    ("Tableau", "https://help.tableau.com/current/api/rest_api", "Business Intelligence"),
    ("Metabase", "https://www.metabase.com/docs/latest/api-documentation.html", "Business Intelligence"),
    ("dbt", "https://docs.getdbt.com/dbt-cloud/api-v2", "Data Engineering"),
    ("Fivetran", "https://fivetran.com/docs/rest-api", "Data Integration"),
    ("Airbyte", "https://reference.airbyte.com", "Data Integration"),

    # HR & Operations
    ("Workday", "https://community.workday.com/api", "HR"),
    ("BambooHR", "https://documentation.bamboohr.com/reference", "HR"),
    ("Greenhouse", "https://developers.greenhouse.io", "Recruiting"),
    ("Lever", "https://hire.lever.co/developer/postings", "Recruiting"),
    ("Gusto", "https://docs.gusto.com", "Payroll"),
    ("Rippling", "https://developer.rippling.com", "HR"),
    ("Lattice", "https://developers.lattice.com", "Performance Management"),
    ("Expensify", "https://integrations.expensify.com", "Expenses"),
    ("Concur", "https://developer.concur.com", "Expenses"),
    ("ServiceNow", "https://developer.servicenow.com", "ITSM"),

    # Storage & Files
    ("Dropbox", "https://www.dropbox.com/developers", "Storage"),
    ("Box", "https://developer.box.com", "Storage"),
    ("Google Drive", "https://developers.google.com/drive/api/guides/about-sdk", "Storage"),
    ("OneDrive", "https://learn.microsoft.com/en-us/onedrive/developer", "Storage"),
    ("Cloudinary", "https://cloudinary.com/documentation/cloudinary_references", "Media"),
    ("Imgix", "https://docs.imgix.com", "Media"),
    ("Loom", "https://dev.loom.com", "Video"),
    ("Vimeo", "https://developer.vimeo.com", "Video"),
    ("YouTube Data API", "https://developers.google.com/youtube/v3", "Video"),
    ("Spotify", "https://developer.spotify.com/documentation/web-api", "Music"),
]


def main() -> None:
    output = Path("data/apps.csv")
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["app_name", "seed_url", "category"])
        for name, url, category in APPS:
            writer.writerow([name, url, category])

    print(f"✓ Generated {len(APPS)} apps → {output}")


if __name__ == "__main__":
    main()
