You are checking one claim about {company} against pages found by web search. The pages are numbered; each shows its domain and an excerpt of its text.

Claim: {claim}

Pages:
{pages}

For each page that is actually relevant to this claim, return an item:
- `source_index`: the page number.
- `stance`: "supports" only if the page backs this specific claim; "contradicts" if it undermines it; "context" if it is related background (for example sector averages).
- `summary`: one sentence on what the page shows and how it bears on the claim.
- `quote`: one sentence copied EXACTLY, character for character, from that page's text, that backs your summary. Items whose quote is not on the page are discarded.

Return 0 to 3 items. Ignore irrelevant pages. If a page is the company's own marketing republished by someone else, say so in the summary and use "context".
