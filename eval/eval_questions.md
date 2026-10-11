# Evaluation questions

Nine Dutch questions for the v1 evaluation set, written against the Dutch texts in `corpus/raw/` (AI-verordening consolidated 27 July 2026, AVG, CRA, Omnibus).

**Identifiers** follow the parsed corpus: `AI-verordening:art_6`, `AI-verordening:anx_III`, `AVG:art_35`, `CRA:art_12`, `Omnibus:rct_40`. The unit is the article or annex, per the chunking rule.

**Expectations.** `must` lists provisions that must be in the final context. `via reference` marks those that the text of another provision names explicitly, so they test the selection step even if vector search misses them. Which ones vector search finds on its own is measured in `docs/EVAL_RESULTS.md`. The quoted Dutch text lets you check each expectation against the source.

| # | Type | Expected behavior | Question |
|---|---|---|---|
| Q01 | lookup | answer | Wat is het verschil tussen een aanbieder en een gebruiksverantwoordelijke volgens de AI-verordening? |
| Q02 | obligations | answer | Moeten wij gebruikers laten weten dat ze met een chatbot praten? |
| Q03 | applicability | answer | Is een AI-systeem dat sollicitaties filtert een AI-systeem met een hoog risico? |
| Q04 | cross-law | answer | Moeten wij een gegevensbeschermingseffectbeoordeling uitvoeren als wij een AI-systeem met een hoog risico in gebruik nemen? |
| Q05 | cross-law | answer | Mogen wij bijzondere categorieën persoonsgegevens verwerken om vooringenomenheid in ons AI-systeem op te sporen? |
| Q06 | cross-law | answer | Als ons AI-systeem ook een product met digitale elementen is, moeten wij dan nog apart aan de cyberbeveiligingseisen van de AI-verordening voldoen? |
| Q07 | deadline | answer | Vanaf wanneer moeten AI-systemen voor het selecteren van sollicitanten aan de eisen voor systemen met een hoog risico voldoen? |
| Q08 | applicability | clarify | Wij gebruiken AI om cv's te screenen. Wat moeten wij doen om aan de regels te voldoen? |
| Q09 | out-of-corpus | cannot_answer | Welke eisen stelt de Colorado AI Act aan bedrijven? |

## Q01. lookup (answer)

**Wat is het verschil tussen een aanbieder en een gebruiksverantwoordelijke volgens de AI-verordening?**
*What is the difference between a provider and a deployer under the AI Act?*

- **Must be in final context:** `AI-verordening:art_3`
- **Notes:** Plain lookup in the largest regular provision (Art. 3, about 5K tokens). Should be answered directly, no clarification.

Source text:

> „aanbieder”: een natuurlijke of rechtspersoon, overheidsinstantie, agentschap of ander orgaan die/dat een AI-systeem of een AI-model voor algemene doeleinden ontwikkelt of laat ontwikkelen en dat systeem of model in de handel brengt of het AI-systeem in gebruik stelt onder de eigen naam of merk, al dan niet tegen betaling;
> *(AI-verordening art. 3, punt 3)*

> „gebruiksverantwoordelijke”: een natuurlijke of rechtspersoon, overheidsinstantie, agentschap of ander orgaan die/dat een AI-systeem onder eigen verantwoordelijkheid gebruikt, tenzij het AI-systeem wordt gebruikt in het kader van een persoonlijke niet-beroepsactiviteit;
> *(AI-verordening art. 3, punt 4)*


## Q02. obligations (answer)

**Moeten wij gebruikers laten weten dat ze met een chatbot praten?**
*Do we have to tell users they are talking to a chatbot?*

- **Must be in final context:** `AI-verordening:art_50`
- **Notes:** The chatbot duty in lid 1 rests on providers. A good answer says so instead of asking for the role. Art. 50 (about 1.3K tokens) is an Omnibus-amended article.

Source text:

> Aanbieders zorgen ervoor dat AI-systemen die voor directe interactie met natuurlijke personen zijn bedoeld, zodanig worden ontworpen en ontwikkeld dat de betrokken natuurlijke personen worden geïnformeerd dat zij interageren met een AI-systeem, tenzij dit duidelijk is vanuit het oogpunt van een normaal geïnformeerde en redelijk omzichtige en oplettende natuurlijke persoon [...]
> *(AI-verordening art. 50, lid 1)*


## Q03. applicability (answer)

**Is een AI-systeem dat sollicitaties filtert een AI-systeem met een hoog risico?**
*Is an AI system that filters job applications a high-risk AI system?*

- **Must be in final context:** `AI-verordening:art_6`, `AI-verordening:anx_III`
- **Reached via reference:** `AI-verordening:anx_III`
- **Notes:** Reference test: Art. 6 points to Annex III, and the actual employment use case only appears in the annex. Tests that the selection step requests the annex if vector search returns only Art. 6.

Source text:

> Naast de in lid 1 bedoelde AI-systemen met een hoog risico worden ook AI-systemen zoals bedoeld in bijlage III als AI-systeem met een hoog risico beschouwd.
> *(AI-verordening art. 6, lid 2)*

> AI-systemen die bedoeld zijn om te worden gebruikt voor het werven of selecteren van natuurlijke personen, met name voor het plaatsen van gerichte vacatures, het analyseren en filteren van sollicitaties, en het beoordelen van kandidaten;
> *(AI-verordening bijlage III, punt 4, a))*

> Niettegenstaande de eerste alinea wordt een in bijlage III bedoeld AI-systeem altijd als een AI-systeem met een hoog risico beschouwd indien het AI-systeem profilering van natuurlijke personen uitvoert.
> *(AI-verordening art. 6, lid 3 (slot))*


## Q04. cross-law (answer)

**Moeten wij een gegevensbeschermingseffectbeoordeling uitvoeren als wij een AI-systeem met een hoog risico in gebruik nemen?**
*Do we have to carry out a data protection impact assessment when we put a high-risk AI system into use?*

- **Must be in final context:** `AI-verordening:art_26`, `AVG:art_35`
- **Reached via reference:** `AVG:art_35`
- **Notes:** Cross-document reference: Art. 26(9) names AVG Art. 35 explicitly. 'In gebruik nemen' already states the deployer role, so no clarification is needed.

Source text:

> Indien van toepassing, gebruiken gebruiksverantwoordelijken van AI-systemen met een hoog risico de informatie die op grond van artikel 13 van deze verordening wordt verstrekt om hun verplichting na te komen om een gegevensbeschermingseffectbeoordeling uit te voeren op grond van artikel 35 van Verordening (EU) 2016/679 [...]
> *(AI-verordening art. 26, lid 9)*

> Wanneer een soort verwerking, in het bijzonder een verwerking waarbij nieuwe technologieën worden gebruikt, [...] waarschijnlijk een hoog risico inhoudt voor de rechten en vrijheden van natuurlijke personen voert de verwerkingsverantwoordelijke vóór de verwerking een beoordeling uit [...]
> *(AVG art. 35, lid 1 (begin))*


## Q05. cross-law (answer)

**Mogen wij bijzondere categorieën persoonsgegevens verwerken om vooringenomenheid in ons AI-systeem op te sporen?**
*May we process special categories of personal data to detect bias in our AI system?*

- **Must be in final context:** `AI-verordening:art_4a`, `AI-verordening:art_10`, `AVG:art_9`
- **Reached via reference:** `AI-verordening:art_10`
- **Notes:** Art. 4 bis was inserted by the Omnibus. It names Art. 10(2)(f) and (g) explicitly (reference test). AVG Art. 9 is not named explicitly in Art. 4 bis, so it is expected from vector search or from the model's own judgement, and is the softest expectation in the set.

Source text:

> Voor zover dit strikt noodzakelijk is om te zorgen voor opsporing en correctie van vooringenomenheid in verband met de AI-systemen met een hoog risico overeenkomstig artikel 10, lid 2, punten f) en g) van deze verordening, mogen de aanbieders van dergelijke systemen bij wijze van uitzondering bijzondere categorieën persoonsgegevens verwerken, mits passende waarborgen worden geboden [...]
> *(AI-verordening art. 4 bis, lid 1)*


## Q06. cross-law (answer)

**Als ons AI-systeem ook een product met digitale elementen is, moeten wij dan nog apart aan de cyberbeveiligingseisen van de AI-verordening voldoen?**
*If our AI system is also a product with digital elements, do we still have to meet the AI Act's cybersecurity requirements separately?*

- **Must be in final context:** `CRA:art_12`, `AI-verordening:art_15`, `AI-verordening:art_42`
- **Reached via reference:** `AI-verordening:art_15`
- **Notes:** Two-way presumption of conformity between CRA and AI Act. Art. 12 CRA names AI Act Art. 15 and Art. 43; Art. 42(3) AI Act points back to CRA Art. 12. Only applies to high-risk systems (Art. 6), which a good answer should say.

Source text:

> Onverminderd de in artikel 15 van Verordening (EU) 2024/1689 vastgestelde vereisten inzake nauwkeurigheid en robuustheid worden producten met digitale elementen die binnen het toepassingsgebied van deze verordening vallen en die op grond van artikel 6 van die verordening als AI-systemen met een hoog risico worden aangemerkt, geacht in overeenstemming te zijn met de in artikel 15 van die verordening vastgestelde cyberbeveiligingsvereisten indien: [...]
> *(CRA art. 12, lid 1 (begin))*

> Wanneer AI-systemen met een hoog risico binnen het toepassingsgebied van Verordening (EU) 2024/2847 vallen en aan de voorwaarden van artikel 12, lid 1, van die verordening is voldaan, worden zij geacht te voldoen aan de cyberbeveiligingsvereisten van artikel 15 van deze verordening.
> *(AI-verordening art. 42, lid 3)*


## Q07. deadline (answer)

**Vanaf wanneer moeten AI-systemen voor het selecteren van sollicitanten aan de eisen voor systemen met een hoog risico voldoen?**
*From when do AI systems for selecting job applicants have to meet the high-risk requirements?*

- **Must be in final context:** `AI-verordening:art_113`, `AI-verordening:anx_III`
- **Reached via reference:** `AI-verordening:anx_III`
- **Optional:** `Omnibus:rct_40`
- **Notes:** Expected answer: 2 December 2027 (Annex III, employment is Annex III point 4). The consolidated Art. 113 already carries the new dates. The Omnibus recital explains why, and is optional context.

Source text:

> hoofdstuk III, de afdelingen 1, 2 en 3, met uitzondering van artikel 6, lid 5, van toepassing met ingang van: i) 2 december 2027 voor wat betreft AI-systemen die op grond van artikel 6, lid 2, en bijlage III als AI-systemen met een hoog risico zijn aangemerkt, en ii) 2 augustus 2028 voor wat betreft AI-systemen die op grond van artikel 6, lid 1, en bijlage I als AI-systemen met een hoog risico zijn aangemerkt;
> *(AI-verordening art. 113, punt c))*

> Artikel 113 van Verordening (EU) 2024/1689 bevat de data van inwerkingtreding en toepassing van die verordening, en hierin wordt met name de algemene datum van toepassing van 2 augustus 2026 vermeld. [...]
> *(Omnibus overweging 40 (begin))*


## Q08. applicability (clarify)

**Wij gebruiken AI om cv's te screenen. Wat moeten wij doen om aan de regels te voldoen?**
*We use AI to screen CVs. What do we have to do to comply?*

- **Must be in final context:** `AI-verordening:art_6`, `AI-verordening:anx_III`, `AI-verordening:art_16`, `AI-verordening:art_26`
- **Reached via reference:** `AI-verordening:anx_III`
- **Optional:** `AI-verordening:art_25`
- **Notes:** Clarification case. 'Gebruiken' does not say whether the company built the system (provider, Art. 16) or bought it (deployer, Art. 26). The expected behavior is one question about the role (and, at most, one about the domain). If the user does not answer, a branched answer covering both roles.

Source text:

> Aanbieders van AI-systemen met een hoog risico: a) zorgen ervoor dat hun AI-systemen met een hoog risico in overeenstemming zijn met de eisen van afdeling 2; [...]
> *(AI-verordening art. 16 (begin))*

> Gebruiksverantwoordelijken van AI-systemen met een hoog risico nemen passende technische en organisatorische maatregelen om te waarborgen dat zij dergelijke systemen gebruiken in overeenstemming met de gebruiksaanwijzingen die bij de systemen zijn gevoegd [...]
> *(AI-verordening art. 26, lid 1)*

> In de volgende omstandigheden wordt een distributeur, importeur, gebruiksverantwoordelijke of derde voor de toepassing van deze verordening beschouwd als een aanbieder van een AI-systeem met een hoog risico en is hij onderworpen aan de verplichtingen van de aanbieder uit hoofde van artikel 16: [...]
> *(AI-verordening art. 25, lid 1 (begin))*


## Q09. out-of-corpus (cannot_answer)

**Welke eisen stelt de Colorado AI Act aan bedrijven?**
*What requirements does the Colorado AI Act place on companies?*

- **Must be in final context:** none
- **Notes:** No provision should pass the similarity threshold. Expected: the tool says it cannot answer, describes what the corpus covers, and makes no LLM call. Also a calibration check for the threshold: it should reject this while still admitting Q01 to Q08.
