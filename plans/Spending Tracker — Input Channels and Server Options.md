# Spending Tracker: Input Channels and Server Options

Status: investigation only. Nothing is built yet. Date of the investigation: 2026-10-06.

## Summary

- With the app on the laptop, the best next channel is email (IMAP). If the owner uses Discord, add Discord after email.
- If the owner accepts the data on a rented server, move the app online behind Tailscale or Cloudflare Access (option B). Then add a camera button and a home screen install to the web app first.
- If the data must stay at home, run the app on an always-on machine at home (option C).
- Use a relay server on a domain (option A) only for one case: WhatsApp is a must, and the data stays on the laptop.

## Criteria

A reliable channel for Spendtrack meets these four criteria:

1. The app gets the messages without a public address. The laptop has no public address.
2. The service keeps the messages while the laptop sleeps, or the app can fetch the missed messages later.
3. The channel carries photos, because the bot reads receipt photos.
4. The channel has an official API. An unofficial client can cause a ban of the account.

## Part 1: Channels with the app on the laptop

| Channel | No public address needed | Laptop asleep | Photos | Official API | Setup | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Telegram (current) | Yes, long polling | Telegram keeps messages for 24 hours | Yes | Yes | Done | Baseline |
| Email (IMAP) | Yes, the app reads the mailbox | Yes, mail stays until the app reads it | Yes, attachments | Yes | Low | Best next channel |
| Discord | Yes, the bot keeps a connection open | The app reads the DM history after a reconnect | Yes | Yes | Low | Good |
| Slack | Yes, Socket Mode | The app reads the DM history after a reconnect | Yes | Yes | Medium | Good if the owner uses Slack |
| Matrix | Yes, long polling | Yes, the server keeps messages | Yes | Yes, open protocol | Medium | Possible |
| WhatsApp | No, Meta sends messages to a public URL | Meta retries for up to 7 days | Yes | Only the Cloud API | High | Possible, much setup |
| Signal | Yes, through signal-cli | Yes | Yes | No, signal-cli is unofficial | Medium | Fragile |
| SMS | No, or a spare Android phone | Depends on the setup | No | Yes | High | Weak in Romania |

### Email

- The Python standard library has `imaplib`, `smtplib` and `email`. The channel needs no new dependency.
- The mail stays in the mailbox until the app reads it. The 24-hour limit of Telegram does not apply.
- The owner can forward e-receipts and invoices, for example from eMAG, Bolt, Glovo or the utilities. Telegram cannot do this.
- Use a separate mailbox. Personal Gmail accepts an app password with 2-Step Verification. Google Workspace no longer accepts basic passwords. Fastmail also works.
- A sender can forge the "From" address. Accept only the address of the owner, and examine the SPF and DKIM result in the `Authentication-Results` header. Another method is a secret address, for example `spendtrack+x7k2@...`.
- The bot replies by email. This is slower than a chat.

### Discord

- The bot keeps a connection to the Discord gateway. It needs no public URL. The service is free. The owner sends a DM to the bot.
- A small bot can turn on the Message Content intent itself, without a review. DMs to the bot carry their text also without the intent.
- Discord does not send the events again after the laptop wakes. On reconnect, the app reads the DM history after the last message ID that it processed.

### Slack

- Socket Mode needs no public URL.
- Slack sends an event again only a few times, within about one hour. After a longer sleep, the app reads the missed messages with `conversations.history`.
- The lower rate limits from 2025-05-29 apply to apps that a company distributes outside the Marketplace. They do not apply to internal apps, so the catch-up works.
- If Slack is already open on the phone of the owner, this channel is useful. Otherwise, do not add it.

### WhatsApp

- Only the official Cloud API is reliable. Unofficial libraries, for example Baileys and whatsapp-web.js, break the terms of service. Meta can ban the number.
- The Cloud API needs a Meta business account and a phone number that is not on WhatsApp yet.
- Meta sends each message to a public HTTPS URL. On the laptop, this needs a tunnel or a relay server. Meta retries for up to 7 days, so a sleeping laptop loses no messages.
- Since 15 January 2026, Meta does not allow general-purpose AI chatbots on the platform. A bot with one business task is allowed. An expense logger has one task, but it is a personal use of a business platform.

### Signal

- signal-cli works, but it is unofficial. It needs a separate phone number.
- A signal-cli version older than three months can stop working. The owner must update it regularly.

### SMS

- Twilio does not support two-way SMS in Romania. An MMS arrives as a text with a link.
- The only practical setup is a spare Android phone with an SMS gateway app.
- SMS does not carry receipt photos.

### Extras for any channel

- An iOS Shortcut or a Siri command can send an email. The entry then uses the email channel and its queue.
- The web app on the phone through Tailscale works, but only while the laptop is awake.

## Part 2: Server options

### Option A: a relay server on a domain, the app stays on the laptop

A small service runs at a public address, for example `in.yourdomain.ro`. It receives the messages from WhatsApp, Slack, email and SMS gateways. It checks the signature of each message, stores the message in a queue, and can reply "Primit" at once. The laptop fetches the queue over HTTPS with a token. Then it parses each message, sends the replies, and tells the relay to delete the message.

Gains:

- WhatsApp Cloud API and Slack Events become simple.
- Email on the own domain becomes possible, for example `bon@yourdomain.ro`, through Cloudflare Email Routing or a Mailgun or Postmark inbound webhook.
- Every channel gets a queue without a time limit.

Costs:

- The app saves an entry and sends the reply only after the laptop wakes. The reply can come hours later.
- The owner has two programs to deploy and to keep compatible.
- The relay holds texts and photos until the laptop collects them.

Verdict: use option A only for one case. WhatsApp is a must, and the data must stay on the laptop.

### Option B: the whole app online

Gains:

- The app is always on. The bot replies within seconds at any hour. The daily backup runs at a fixed time.
- The web app becomes the main entry on the phone:
  - Add a web app manifest, so that the owner can install the app on the home screen.
  - Add a camera button on the Add page with `<input type="file" accept="image/*" capture>`. The photo goes to the receipt parser. This works on iPhone and Android.
  - On Android, the Web Share Target API puts Spendtrack in the share menu. iOS Safari does not support it.
  - With these changes, more chat channels can become unnecessary.
- Every channel that sends messages to a URL works directly: WhatsApp, Slack Events and inbound email on the own domain. Telegram can keep long polling without a change.

Required changes:

1. Access control. Today the app has only Basic Auth. The app turns it on only with `ALLOW_REMOTE` set. The password check uses `compare_digest`. On the open internet, two protections are missing:
   - A rate limit. Nothing stops an attacker who guesses passwords.
   - CSRF (cross-site request forgery) protection. The browser sends the Basic Auth credentials again on form posts from other websites. The app has no CSRF token.

   Put an access layer in front of the app: Tailscale (only the devices of the owner can connect) or Cloudflare Access. Then the app is online but not public. Only the webhook paths stay public, each with its signature check.
2. HTTPS. Use Traefik with Let's Encrypt. If the owner still has the Hetzner server with Traefik, Spendtrack fits there as one more Docker container.
3. Deployment. Add a Dockerfile, a volume for `DATA_DIR` and a health check. The server mode does not need the browser launcher or the launchd agent.
4. Backups. Today the app writes them to the same `DATA_DIR`. On a server, copy them to another place each day, for example with restic or rclone to object storage, or to the laptop.
5. Privacy. The expense data and the API keys move to a rented server. Update the privacy section of the README and the "local only" principle of the MVP specification.
6. Database. SQLite is enough for one user. Postgres is not necessary.

### Option C: an always-on machine at home

Run the app on a Mac mini, a Raspberry Pi or a NAS (network-attached storage). Use Tailscale for the phone. If a channel needs a public URL, add Cloudflare Tunnel. The data stays at home, and the app is always on without a rented server. The risks are a power cut and an outage of the home internet.

## Channels in each setup

| Channel | Laptop only (today) | Laptop with relay (A) | Online (B) or home machine (C) |
| --- | --- | --- | --- |
| Web app on the phone | Only while the laptop is awake | Same as today | Yes, the best entry |
| Telegram | Yes | Yes | Yes, with instant replies |
| Email | IMAP mailbox | Own domain | Own domain |
| Discord and Slack | Catch-up from the history | Yes | Yes |
| WhatsApp | No | Yes, with late replies | Yes |
| SMS | Weak, no two-way SMS at Twilio in Romania | Same as today | Same as today |

## Open decisions

1. Can the expense data live on a rented server (option B)? Or must it stay at home (option C) or on the laptop?
2. Is WhatsApp a must?
3. Which chat apps does the owner open on the phone every day: Discord, Slack or others?

## Facts in the code on 2026-10-06

- The AI parse (`spendtrack/core/ai_parse.py`) and the core save functions work for any channel.
- `BotService` and `parse_update` in `spendtrack/bot/service.py` work only with Telegram.
- The `inbound_message` table has Telegram columns: `tg_update_id`, `tg_chat_id` and `tg_message_id`.
- Each new channel needs an adapter that fetches the messages, downloads the attachments and sends the replies.
- Before the second channel, change `inbound_message` with a migration to a channel name and an external ID.
- With that base, the email channel is about one day of work. Discord and Slack each need a library (`discord.py`, `slack_bolt`) and a catch-up step.
- The web app has no web app manifest and no service worker.

## Sources

- [respond.io: WhatsApp general-purpose chatbots ban](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban)
- [Meta: WhatsApp No Storage and webhook retries](https://developers.facebook.com/documentation/business-messaging/whatsapp/no-storage/)
- [Slack: rate limit changes for non-Marketplace apps](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps)
- [Slack: 2025-05 terms and rate limit FAQ](https://api.slack.com/changelog/2025-05-terms-rate-limit-update-and-faq)
- [Twilio: Romania SMS guidelines](https://www.twilio.com/en-us/guidelines/ro/sms)
- [signal-cli releases](https://releasealert.dev/github/AsamK/signal-cli)
- [Mailbird: Gmail OAuth changes 2026](https://www.getmailbird.com/gmail-oauth-authentication-changes-user-guide/)
- [Red-DiscordBot documentation: privileged intents](https://red-discordbot-audio.readthedocs.io/en/latest/intents.html)
