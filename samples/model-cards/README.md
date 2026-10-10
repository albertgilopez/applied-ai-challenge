# Model cards

Local copies of the model cards the sample SBOM points at, trimmed to the front matter and the license
sections. They are read by `agent/model_cards.py` instead of the network: two of the three models
(Llama 3.1, Gemma 2) are gated on the host, so their cards cannot be fetched anonymously.

File name: `<org>__<name>.md` for the model id `<org>/<name>`. The two `example__*` cards are fixtures
for the cases with no license and with a rejected license.
