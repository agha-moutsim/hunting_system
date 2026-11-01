# Performance and timeout policy

- Analyze pipeline ceiling: 150 seconds.
- Each stage has its own budget and reports overrun in `timing` / `budget`.
- Deep Search fast targets ~15-20 seconds.
- Full Deep Search uses a background job and polling.
- Bulk runs queries sequentially; one failed query does not stop the rest.
- Supplier scrapes are bounded; timeouts are reported as timed out, not as zero.
- Ollama `num_predict` is 500; thinking mode is disabled for JSON generation.