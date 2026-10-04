# Configurer les alertes

Les seuils CPU, RAM, disque, le délai entre les alertes et la durée de conservation des métriques se configurent depuis **Réglages** dans le tableau de bord.

La collecte s'exécute toutes les cinq minutes. Lorsqu'un seuil est atteint, l'application envoie au maximum une alerte par métrique pendant le délai configuré.

Les secrets des canaux d'alerte restent dans `.env`, jamais dans l'interface ni dans Git.

## Discord

Créez un webhook Discord pour le salon souhaité, puis ajoutez :

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

## Telegram

Créez un bot avec BotFather, récupérez son token et l'identifiant du chat :

```env
TELEGRAM_BOT_TOKEN=123456:token_du_bot
TELEGRAM_CHAT_ID=123456789
```

## E-mail SMTP

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=monitor@example.com
SMTP_PASSWORD=mot_de_passe_ou_mot_de_passe_application
ALERT_EMAIL_FROM=monitor@example.com
ALERT_EMAIL_TO=admin@example.com
```

Après toute modification de `.env`, redémarrez le service :

```bash
sudo systemctl restart linux-monitor
```
