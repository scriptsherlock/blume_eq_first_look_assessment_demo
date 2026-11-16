You are preparing the analyst for the next call with the founder of {company}.

The model's assumptions, ranked by how much each one moves the result (rank 1 moves it most):
{ranked}

Open objections from the investment committee:
{objections}

Write 5 questions to ask the founder (fewer if there are fewer than 5 assumptions worth asking about). Each must:
- target a **different** assumption by id (prefer high-ranked judgement calls and assumptions with severe objections; skip pure unit conversions),
- ask for the underlying data, never ask the founder to justify a number our model assumed (they did not make it),
- ask for something the founder can actually answer or send (a number, a definition, a customer reference, a data extract),
- be one sentence, specific and polite.

`sensitivity_rank` is the rank of the targeted assumption. `why_it_matters` says in one sentence what the answer would change. Ids q1..q5, ordered by importance.
