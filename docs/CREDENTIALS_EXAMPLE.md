# Локальное хранение ключей

Файл `~/.marketplace-mcp/cabinets.json` находится **вне** клона Git. Пример со значениями-заглушками:

```json
{
  "wb": {"active": "main", "cabinets": {"main": {"token": "YOUR_WB_TOKEN"}}},
  "ozon": {"active": "main", "cabinets": {"main": {"client_id": "YOUR_OZON_CLIENT_ID", "api_key": "YOUR_OZON_API_KEY"}}},
  "ozon_perf": {"active": "main", "cabinets": {"main": {"client_id": "YOUR_PERF_CLIENT_ID", "client_secret": "YOUR_PERF_CLIENT_SECRET"}}}
}
```

На Mac ограничьте доступ: `chmod 700 ~/.marketplace-mcp` и `chmod 600 ~/.marketplace-mcp/cabinets.json`. Не отправляйте содержимое файла в чат, на GitHub или в поддержку. Не используйте реальные значения при проверке тестов.
