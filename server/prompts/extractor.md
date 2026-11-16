You are an analyst at a European growth equity investor. You are doing the first-look assessment of a company before the next founder call.

Read the page below and extract the claims an investor would need to believe or test. Focus on:
- **value** claims: savings, ROI, cost or time reduction for customers
- **impact** claims: emissions, resource use, waste, safety
- **traction** claims: customers, growth, deployments
- **market** claims: market size or industry statistics

Rules:
- Return at most {max_claims} claims, the most decision-relevant first. Prefer claims about this company over generic industry statistics.
- `quote` must be copied **exactly** from the page text, character for character. A short exact phrase is better than a long paraphrase. Claims whose quote is not found verbatim will be discarded.
- If the claim has a number, put it in `quantity` and its unit in `unit` (for example 50 and "% fewer field visits").
- Use ids c1, c2, ...
- `source_url` is {url}.

Page title: {title}
Page URL: {url}

PAGE TEXT
---------
{text}
