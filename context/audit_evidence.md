# נספח A — מיפוי שדות וראיות מקוריות

> סביבת GTM סינתטית; תאריך ייחוס עסקי 13.9.2026. ריק = ערך שאינו מופיע בתשובת הרשומה; מספרים מחושבים מכל הרשומות שנשלפו.

## שדות Airtable

| טבלה | שדה | סוג | מלא | שיעור |
|---|---|---|---:|---:|
| Companies | Company Name | singleLineText | 66/66 | 100% |
| Companies | Company ID | number | 66/66 | 100% |
| Companies | Inventory Prioritization | singleLineText | 0/66 | 0% |
| Companies | Logo | singleLineText | 0/66 | 0% |
| Companies | Notable Features | multipleSelects | 66/66 | 100% |
| Companies | Country | singleSelect | 49/66 | 74% |
| Companies | Notes | multilineText | 38/66 | 58% |
| Companies | Industry | singleSelect | 66/66 | 100% |
| Companies | Lead Source | singleSelect | 66/66 | 100% |
| Companies | Created Date | date | 66/66 | 100% |
| Companies | Company Summary | multilineText | 0/66 | 0% |
| Companies | Company Insights (AI) | multilineText | 0/66 | 0% |
| Companies | Priority | singleSelect | 49/66 | 74% |
| Companies | Select | singleSelect | 0/66 | 0% |
| Companies | Inventory Carrying Cost ($M) | number | 14/66 | 21% |
| Companies | Inventory Cost as % of EBITDA | percent | 14/66 | 21% |
| Companies | Planning System | singleLineText | 14/66 | 21% |
| Companies | Pilots | singleLineText | 4/66 | 6% |
| Companies | Primary Contact | multipleRecordLinks | 66/66 | 100% |
| Companies | Related Deals | multipleRecordLinks | 5/66 | 8% |
| Contacts | Full Name | singleLineText | 187/187 | 100% |
| Contacts | Contact ID | number | 187/187 | 100% |
| Contacts | First Name | singleLineText | 187/187 | 100% |
| Contacts | Last Name | singleLineText | 187/187 | 100% |
| Contacts | Title | singleLineText | 187/187 | 100% |
| Contacts | Email | email | 73/187 | 39% |
| Contacts | Initial Subject | singleLineText | 179/187 | 96% |
| Contacts | Email Status | singleSelect | 187/187 | 100% |
| Contacts | Lead Status | singleSelect | 187/187 | 100% |
| Contacts | Initial Email Body | multilineText | 80/187 | 43% |
| Contacts | Event App Message | multilineText | 11/187 | 6% |
| Contacts | AI Assessment (/10) | number | 80/187 | 43% |
| Contacts | AI Feedback | multilineText | 80/187 | 43% |
| Contacts | Follow-Up Email Body | multilineText | 31/187 | 17% |
| Contacts | Follow-Up Email Subject | singleLineText | 31/187 | 17% |
| Contacts | Follow-Up Email Attachment | singleLineText | 0/187 | 0% |
| Contacts | Company | multipleRecordLinks | 187/187 | 100% |
| Contacts | Deals | multipleRecordLinks | 5/187 | 3% |
| Activities | Activity | singleLineText | 0/0 | — |
| Activities | Type | singleSelect | 0/0 | — |
| Activities | Date | date | 0/0 | — |
| Activities | Notes | multilineText | 0/0 | — |
| Activities | Deal | multipleRecordLinks | 0/0 | — |
| Deals | Deal ID | singleLineText | 5/5 | 100% |
| Deals | Deal Name | singleLineText | 5/5 | 100% |
| Deals | Deal Stage | singleSelect | 5/5 | 100% |
| Deals | Amount | currency | 2/5 | 40% |
| Deals | Close Date | date | 5/5 | 100% |
| Deals | Created Date | date | 5/5 | 100% |
| Deals | Stage Entered Date | date | 3/5 | 60% |
| Deals | Lead Source | singleSelect | 5/5 | 100% |
| Deals | Industry | singleSelect | 5/5 | 100% |
| Deals | Deal Photo | singleLineText | 0/5 | 0% |
| Deals | Notes | multilineText | 1/5 | 20% |
| Deals | Deal Summary (AI) | multilineText | 0/5 | 0% |
| Deals | Win Probability (AI) | singleLineText | 0/5 | 0% |
| Deals | Company | multipleRecordLinks | 5/5 | 100% |
| Deals | Primary Contact | multipleRecordLinks | 5/5 | 100% |
| Deals | Activities | multipleRecordLinks | 0/5 | 0% |

## הערכת אמינות לכל שדה

הציון מתייחס ליכולת להשתמש בערך כפי שהוא למדידת GTM; גם שדה ‘גבוהה’ אינו תחליף לאימות חוזה. השדות המלאים מספרית אך לא תקפים כאירועים מסומנים במפורש.

| טבלה | שדה | אמינות למדידת GTM | סיבה קצרה |
|---|---|---|---|
| Companies | Company Name | בינונית לזהות | כתיב ו־alias/כפילות דורשים איחוד |
| Companies | Company ID | גבוהה למזהה | ייחודי בתוך הטבלה; זהות חוצת־מקורות לא מוכחת |
| Companies | Inventory Prioritization | אין ראיה | ריק בכל הרשומות |
| Companies | Logo | אין ראיה | ריק בכל הרשומות |
| Companies | Notable Features | בינונית | סיווג לצורכי פילוח; חלקו תווית/הערכה |
| Companies | Country | בינונית | סיווג לצורכי פילוח; חלקו תווית/הערכה |
| Companies | Notes | בינונית כראיה גולמית | כולל תצפיות, השערות AI ונתונים סותרים |
| Companies | Industry | בינונית | סיווג לצורכי פילוח; חלקו תווית/הערכה |
| Companies | Lead Source | בינונית | סיווג מקור, לא הוכחת פגישה |
| Companies | Created Date | בינונית כרשומת CRM | אינו encounter; שני Deals נוצרו אחרי stage |
| Companies | Company Summary | אין ראיה | ריק בכל הרשומות |
| Companies | Company Insights (AI) | אין ראיה | ריק בכל הרשומות |
| Companies | Priority | נמוכה | דירוג פנימי ללא הגדרה/תאריך |
| Companies | Select | אין ראיה | ריק בכל הרשומות |
| Companies | Inventory Carrying Cost ($M) | נמוכה עד בינונית | כיסוי סלקטיבי; אין מקור חיצוני מאומת |
| Companies | Inventory Cost as % of EBITDA | נמוכה עד בינונית | כיסוי סלקטיבי; אין מקור חיצוני מאומת |
| Companies | Planning System | נמוכה עד בינונית | כיסוי סלקטיבי; אין מקור חיצוני מאומת |
| Companies | Pilots | נמוכה כאירוע | טקסט חופשי ללא חתימה/מועד |
| Companies | Primary Contact | גבוהה לקישור פנימי | קישור מזהה; אינו קישור ל־Notion |
| Companies | Related Deals | גבוהה לקישור פנימי | קישור מזהה; אינו קישור ל־Notion |
| Contacts | Full Name | בינונית לזהות | כתיב ו־alias/כפילות דורשים איחוד |
| Contacts | Contact ID | גבוהה למזהה | ייחודי בתוך הטבלה; זהות חוצת־מקורות לא מוכחת |
| Contacts | First Name | בינונית לזהות | כתיב ו־alias/כפילות דורשים איחוד |
| Contacts | Last Name | בינונית לזהות | כתיב ו־alias/כפילות דורשים איחוד |
| Contacts | Title | בינונית | תפקיד עצמי ב־CRM ללא מועד אימות |
| Contacts | Email | בינונית לערוץ | חסר ברוב האנשים; כפילויות |
| Contacts | Initial Subject | נמוכה כאירוע | טיוטה ללא sent_at/response |
| Contacts | Email Status | בינונית לערוץ | תוקף כתובת אינו תגובת לקוח |
| Contacts | Lead Status | בינונית כמצב נוכחי | אין תאריך מעבר; כפילויות מציגות מצבים שונים |
| Contacts | Initial Email Body | נמוכה כאירוע | טיוטה ללא sent_at/response |
| Contacts | Event App Message | נמוכה כאירוע | טיוטה ללא sent_at/response |
| Contacts | AI Assessment (/10) | נמוכה לאמת עסקית | דעת מודל, לא הסתברות מכוילת |
| Contacts | AI Feedback | נמוכה לאמת עסקית | ביקורת על נוסח הודעה יוצאת |
| Contacts | Follow-Up Email Body | נמוכה כאירוע | טיוטה ללא sent_at/response |
| Contacts | Follow-Up Email Subject | נמוכה כאירוע | טיוטה ללא sent_at/response |
| Contacts | Follow-Up Email Attachment | אין ראיה | ריק בכל הרשומות |
| Contacts | Company | גבוהה לקישור פנימי | קישור מזהה; אינו קישור ל־Notion |
| Contacts | Deals | גבוהה לקישור פנימי | קישור מזהה; אינו קישור ל־Notion |
| Activities | Activity | אין ראיה | ריק בכל הרשומות |
| Activities | Type | אין ראיה | ריק בכל הרשומות |
| Activities | Date | אין ראיה | ריק בכל הרשומות |
| Activities | Notes | אין ראיה | ריק בכל הרשומות |
| Activities | Deal | אין ראיה | ריק בכל הרשומות |
| Deals | Deal ID | גבוהה למזהה | ייחודי בתוך הטבלה; זהות חוצת־מקורות לא מוכחת |
| Deals | Deal Name | בינונית לזהות | כתיב ו־alias/כפילות דורשים איחוד |
| Deals | Deal Stage | נמוכה כהיסטוריה | snapshot; Westra סותר הערה מאוחרת |
| Deals | Amount | נמוכה ללא סמנטיקת חוזה | 2/5; כנראה rollout שנתי, לא pilot/חתימה |
| Deals | Close Date | נמוכה כביצוע | כל החמישה עתידיים; תחזית |
| Deals | Created Date | בינונית כרשומת CRM | אינו encounter; שני Deals נוצרו אחרי stage |
| Deals | Stage Entered Date | נמוכה | חסר ומוקדם מ־Created Date בשני Deals |
| Deals | Lead Source | בינונית | סיווג מקור, לא הוכחת פגישה |
| Deals | Industry | בינונית | סיווג לצורכי פילוח; חלקו תווית/הערכה |
| Deals | Deal Photo | אין ראיה | ריק בכל הרשומות |
| Deals | Notes | בינונית כראיה גולמית | כולל תצפיות, השערות AI ונתונים סותרים |
| Deals | Deal Summary (AI) | אין ראיה | ריק בכל הרשומות |
| Deals | Win Probability (AI) | אין ראיה | ריק בכל הרשומות |
| Deals | Company | גבוהה לקישור פנימי | קישור מזהה; אינו קישור ל־Notion |
| Deals | Primary Contact | גבוהה לקישור פנימי | קישור מזהה; אינו קישור ל־Notion |
| Deals | Activities | אין ראיה | ריק בכל הרשומות |

## כל 111 דפי Meeting notes ב־Notion

הטקסט להלן הוא גוף הדף שנקרא, כולל תאריך ה־Date ושיוך הטיפוס אם קיים. מזהי יצירה/עריכה של העותק אינם תאריכי אירוע.

### 2025-11-04 · Holmen Parts sync

מקור: https://app.notion.com/p/b1b275a3be238388b0860193ecde60ab?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- spare-parts shortages slow repairs - Lars says this costs them real money
- Setup: vendor EAM + in-house optimisation
- critical spares vs consumables
- Polite, not urgent. 'Interesting research'
- Next: send materials, ping in a few weeks

### 2025-11-21 · Coldharbour

מקור: https://app.notion.com/p/176275a3be2382b39ba101d3f30de393?pvs=204 · Meeting type: Follow-up

#### Agenda
#### Notes
- expiry write-offs stuck ~1.4% - Juhani says this costs them real money
- Setup: ERP with fixed reorder schedules
- seasonal vaccines with spiky demand
- Keen - wants the benchmark result on their data
- Next: send one-pager, book scoping w/ Juhani's team

### 2025-12-01 · Coldharbour

מקור: https://app.notion.com/p/167275a3be238300a204816cd02399d4?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: ERP with fixed reorder schedules
- Pilot scope: one distribution centre
- seasonal vaccines with spiky demand
- Budget: pilot ~€115k, rollout maybe €580k/yr if it works

### 2025-12-07 · Verdant <> Vendora

מקור: https://app.notion.com/p/d34275a3be238242afc501cea22aaf15?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- changeovers take too long - Margaux says this costs them real money
- Setup: MRP software + data lake
- forecast transfer across product lines
- Keen - wants the benchmark result on their data
- Next: send one-pager, book scoping w/ Margaux's team

### 2025-12-10 · Call w/ Annika

מקור: https://app.notion.com/p/0e6275a3be238357b40101a6fc55ac50?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- changeovers take too long - Annika says this costs them real money
- Setup: MRP software + data lake
- forecast transfer across product lines
- Keen - wants the benchmark result on their data
- Next: send one-pager, book scoping w/ Annika's team

### 2025-12-12 · Coldharbour <> Vendora

מקור: https://app.notion.com/p/4c0275a3be2382dcb3720188a93e9acf?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: no stock shipped past its expiry window
- Pilot scope: one distribution centre
- seasonal vaccines with spiky demand

### 2025-12-27 · Call w/ Juhani

מקור: https://app.notion.com/p/989275a3be238307958c81872fc4e365?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Integration: ERP with fixed reorder schedules
- Pilot scope: one distribution centre
- seasonal vaccines with spiky demand
- Budget: pilot ~€115k, rollout maybe €580k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-01-02 · Verdant

מקור: https://app.notion.com/p/8ac275a3be2383bbac3b81c308818fa7?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: order data ~4,000 SKUs
- Pilot scope: one production line
- forecast transfer across product lines
- Budget: pilot ~€90k, rollout maybe €185k/yr if it works

### 2026-01-05 · GB <> Vendora

מקור: https://app.notion.com/p/248275a3be2382cebfe281e83890d5d7?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: never exceed cold-storage capacity
- Pilot scope: one production line
- forecast transfer across product lines
- Budget: pilot ~€75k, rollout maybe €180k/yr if it works

### 2026-01-07 · Coldharbour

מקור: https://app.notion.com/p/ef7275a3be2382b4844b0161250d9b77?pvs=204 · Meeting type: Pilot sync

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €115k, 11 weeks
- Scope: one distribution centre
- Success = write-off reduction in shadow mode, zero violations of 'no stock shipped past its expiry window'

### 2026-01-12 · Verdant Creamery <> Vendora

מקור: https://app.notion.com/p/8e8275a3be2382fc8966815093450e46?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Hard constraint: never exceed cold-storage capacity
- Pilot scope: one production line
- forecast transfer across product lines
- Budget: pilot ~€90k, rollout maybe €185k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-01-21 · Granfield

מקור: https://app.notion.com/p/0e1275a3be238300a43f81d46bb1a67b?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: MRP software + data lake
- Pilot scope: one production line
- forecast transfer across product lines

### 2026-01-28 · Call w/ Margaux

מקור: https://app.notion.com/p/d99275a3be238344ae008189f6f62077?pvs=204 · Meeting type: חסר

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €90k, 15 weeks
- Scope: one production line
- Success = waste reduction in shadow mode, zero violations of 'never exceed cold-storage capacity'

### 2026-02-06 · Coldharbour

מקור: https://app.notion.com/p/a89275a3be2382d7a53a0155338c9f51?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 4. next: interim results to their VP

### 2026-02-06 · Call w/ Annika

מקור: https://app.notion.com/p/e82275a3be238287ac298104ce9a063c?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Hard constraint: never exceed cold-storage capacity
- Pilot scope: one production line
- forecast transfer across product lines
- Budget: pilot ~€75k, rollout maybe €180k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-02-18 · Lone Pine

מקור: https://app.notion.com/p/a10275a3be238341b8b281195b027496?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Short call, distracted
- Derek has gone quiet - may be changing role
- chase in 2 weeks

### 2026-02-21 · Granfield Bakeries

מקור: https://app.notion.com/p/bd1275a3be2382c698a981f48b4ac0eb?pvs=204 · Meeting type: חסר

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €75k, 10 weeks
- Scope: one production line
- Success = waste reduction in shadow mode, zero violations of 'never exceed cold-storage capacity'

### 2026-02-27 · Verdant Creamery <> Vendora

מקור: https://app.notion.com/p/45b275a3be2382cdb6638119ffdbfaf2?pvs=204 · Meeting type: Pilot sync

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 4. next: weekly review with ops

### 2026-03-02 · Aldwin

מקור: https://app.notion.com/p/fba275a3be2383b5b06e811c07173834?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - security review blocked data leaving site
- Helena open to revisit next year

### 2026-03-03 · Tamaro <> Vendora

מקור: https://app.notion.com/p/8e3275a3be238220bdde811c04a87408?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- ordering rules nobody fully understands - Alejandro says this costs them real money
- Setup: commercial ERP with ~400 custom reorder rules
- supplier lead times matter
- Keen - wants the benchmark result on their data
- Next: send one-pager, book scoping w/ Alejandro's team

### 2026-03-08 · Kohana Foodhalls

מקור: https://app.notion.com/p/54e275a3be23839e857d81e2ab7c8e78?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - building in-house with their data science team
- Hideo open to revisit next year

### 2026-03-08 · Call w/ Juhani

מקור: https://app.notion.com/p/fb3275a3be2382c697e101da3637f3a0?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Guardrail flagged some proposed orders that would've broken a hard constraint - they liked that
- wk 8. next: weekly review with ops

### 2026-03-09 · Kumano

מקור: https://app.notion.com/p/cca275a3be23837aafc081bafe30288a?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- carrying costs up sharply YoY - Natsuki says this costs them real money
- Setup: new WMS rollout
- customer-level fill-rate KPIs
- Polite, not urgent. 'Interesting research'
- Next: send materials, ping in a few weeks

### 2026-03-11 · Call w/ Tiago

מקור: https://app.notion.com/p/237275a3be2383c29e6a81e99ea604b8?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- auto-replenishment switched off because planners don't trust it - Tiago says this costs them real money
- Setup: two-vendor WMS + vendor planning suite
- safety stock vs cross-docking
- Keen - wants a deep dive with their engineers
- Next: send one-pager, book scoping w/ Tiago's team

### 2026-03-11 · Ardent <> Vendora

מקור: https://app.notion.com/p/46c275a3be238381af7081b80916ed08?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- vendor planning features are black boxes - Graham says this costs them real money
- Setup: two-vendor WMS + vendor planning suite
- multi-warehouse allocation conflicts
- Keen - wants to see the guardrail design
- Next: send one-pager, book scoping w/ Graham's team

### 2026-03-14 · Mosel Fracht <> Vendora

מקור: https://app.notion.com/p/ce4275a3be2382618b248124696b9f1b?pvs=204 · Meeting type: Follow-up

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- carrying costs up sharply YoY - Felix says this costs them real money
- Setup: home-grown scripts on stock reports
- multi-warehouse allocation conflicts
- Keen - wants a deep dive with their engineers
- Next: send one-pager, book scoping w/ Felix's team

### 2026-03-22 · Rhona

מקור: https://app.notion.com/p/0f0275a3be238219b61701787648083b?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- carrying costs up sharply YoY - Jonas says this costs them real money
- Setup: new WMS rollout
- multi-warehouse allocation conflicts
- Keen - wants to see the guardrail design
- Next: send one-pager, book scoping w/ Jonas's team

### 2026-03-23 · Granfield Bakeries <> Vendora

מקור: https://app.notion.com/p/c13275a3be2383598732814c7674ddf5?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Blocked ~2 weeks on data export, unblocked now
- wk 4. next: interim results to their VP

### 2026-03-26 · Call w/ Felix

מקור: https://app.notion.com/p/9cf275a3be23823fae46813daac8023a?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Data: daily stock-level feeds
- Pilot scope: 3-warehouse cluster
- multi-warehouse allocation conflicts
- Budget: pilot ~€185k, rollout maybe €580k/yr if it works

### 2026-03-28 · Tamaro Supermarkets followup

מקור: https://app.notion.com/p/556275a3be23829ab45301ec8b44e30c?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: shelf-life limits on fresh lines are hard constraints
- Pilot scope: one store region
- promotions break the heuristics
- Budget: pilot ~€150k, rollout maybe €770k/yr if it works

### 2026-03-28 · Ardent

מקור: https://app.notion.com/p/8b2275a3be23823f9d95015004e0741a?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: every transfer order reversible before dispatch
- Pilot scope: 3-warehouse cluster
- customer-level fill-rate KPIs
- Budget: pilot ~€100k, rollout maybe €395k/yr if it works

### 2026-03-29 · Quorra <> Vendora

מקור: https://app.notion.com/p/0f2275a3be23833992ff814c18aa80ff?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: 12 months shipment history
- Pilot scope: 3-warehouse cluster
- customer-level fill-rate KPIs
- Budget: pilot ~€210k, rollout maybe €1M/yr if it works

### 2026-03-29 · Nordahl Distribution

מקור: https://app.notion.com/p/f02275a3be2382149105019c53fdc9c7?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: fill rate never below SLA
- Pilot scope: 3-warehouse cluster
- customer-level fill-rate KPIs
- Budget: pilot ~€185k, rollout maybe €930k/yr if it works

### 2026-03-29 · Call w/ Margaux

מקור: https://app.notion.com/p/f8f275a3be2382b1832801c1507e09b8?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Guardrail flagged some proposed orders that would've broken a hard constraint - they liked that
- wk 8. next: weekly review with ops

### 2026-04-02 · Rhona

מקור: https://app.notion.com/p/f8f275a3be2382b7a2b6018e82c71734?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: fill rate never below SLA
- Pilot scope: shadow-mode planning on 500 SKUs
- multi-warehouse allocation conflicts
- Budget: pilot ~€95k, rollout maybe €400k/yr if it works

### 2026-04-04 · Kumano <> Vendora

מקור: https://app.notion.com/p/1e8275a3be2383eeb0cd01ae03900bff?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - building in-house with their data science team
- Natsuki open to revisit next year

### 2026-04-07 · Coldharbour <> Vendora

מקור: https://app.notion.com/p/b0c275a3be2382c292678115f4ce6736?pvs=204 · Meeting type: Pilot sync

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 12. next: second scenario

### 2026-04-08 · Nordahl

מקור: https://app.notion.com/p/98b275a3be23830bb543019b97e24ea6?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: fill rate never below SLA
- Pilot scope: regional warehouses in one country
- inventory per SKU per week

### 2026-04-09 · Ardent sync

מקור: https://app.notion.com/p/32d275a3be23830db2f7812d94b34201?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Integration: two-vendor WMS + vendor planning suite
- Pilot scope: regional warehouses in one country
- they want it in the WMS not as a separate tool

### 2026-04-09 · Call w/ Felix

מקור: https://app.notion.com/p/db9275a3be238213afb901447d58c3d8?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: every transfer order reversible before dispatch
- Pilot scope: 3-warehouse cluster
- fill-rate impact must be ~zero
- Budget: pilot ~€185k, rollout maybe €580k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-04-11 · Call w/ Alejandro

מקור: https://app.notion.com/p/0e8275a3be2383eaa48f019273cdc03c?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: in-house ERP + spreadsheet replenishment
- Pilot scope: one store region
- want to see the benchmark result extended to fresh categories

### 2026-04-11 · Quorra Supply

מקור: https://app.notion.com/p/ca2275a3be2382939bcb01c1ca436b4f?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Integration: two-vendor WMS + vendor planning suite
- Pilot scope: shadow-mode planning on 500 SKUs
- fill-rate impact must be ~zero

### 2026-04-16 · Rhona <> Vendora

מקור: https://app.notion.com/p/a4a275a3be238215bdff8113faebbb38?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: warehouse cost data
- Pilot scope: regional warehouses in one country
- safety stock vs cross-docking

### 2026-04-19 · Call w/ Chiara

מקור: https://app.notion.com/p/63e275a3be2382338efb811cd5b62e5c?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- reorder points hand-tuned per store - Chiara says this costs them real money
- Setup: in-house ERP + spreadsheet replenishment
- promotions break the heuristics
- Keen - wants a deep dive with their engineers
- Next: send one-pager, book scoping w/ Chiara's team

### 2026-04-20 · Call w/ Tiago

מקור: https://app.notion.com/p/b6c275a3be2383ad85790167020ab0a8?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: every transfer order reversible before dispatch
- Pilot scope: regional warehouses in one country
- safety stock vs cross-docking
- Budget: pilot ~€210k, rollout maybe €1M/yr if it works
- Needs to go to their budget committee

### 2026-04-21 · Tamaro

מקור: https://app.notion.com/p/5b5275a3be23834e861f814870eacca5?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Data: POS sales history
- Pilot scope: one product family, shadow mode
- promotions break the heuristics
- Budget: pilot ~€150k, rollout maybe €770k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-04-22 · Call w/ Annika

מקור: https://app.notion.com/p/6b4275a3be23831ab4d081c7891b4369?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 8. next: weekly review with ops

### 2026-04-24 · Mosel Fracht

מקור: https://app.notion.com/p/03a275a3be23821c89250164094bae0f?pvs=204 · Meeting type: חסר

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €185k, 13 weeks
- Scope: regional warehouses in one country
- Success = on-time-in-full improvement in shadow mode, zero violations of 'fill rate never below SLA'

### 2026-04-24 · Nordahl

מקור: https://app.notion.com/p/e18275a3be2383138d3c81b370b444c0?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: home-grown scripts on stock reports
- Pilot scope: regional warehouses in one country
- fill-rate impact must be ~zero
- Budget: pilot ~€185k, rollout maybe €930k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-04-25 · Call w/ Graham

מקור: https://app.notion.com/p/b54275a3be238315bd1d010a9a01a149?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: two-vendor WMS + vendor planning suite
- Pilot scope: 3-warehouse cluster
- customer-level fill-rate KPIs
- Budget: pilot ~€100k, rollout maybe €395k/yr if it works
- Needs to go to their budget committee

### 2026-04-28 · Call w/ Margaux

מקור: https://app.notion.com/p/b2c275a3be23820fb407819917b2de24?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Shadow policy: 12% less finished-goods waste
- wk 12. next: second scenario

### 2026-04-30 · Rhona followup

מקור: https://app.notion.com/p/49c275a3be23823f90aa81c3b0936301?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: 12 months shipment history
- Pilot scope: shadow-mode planning on 500 SKUs
- multi-warehouse allocation conflicts
- Budget: pilot ~€95k, rollout maybe €400k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-04-30 · TS <> Vendora

מקור: https://app.notion.com/p/b3a275a3be2382078b7181604d857a2a?pvs=204 · Meeting type: חסר

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €150k, 16 weeks
- Scope: one store region
- Success = on-shelf availability improvement in shadow mode, zero violations of 'no order to a supplier outside the approved list'

### 2026-05-03 · MM

מקור: https://app.notion.com/p/79f275a3be23824cb0ea81356dd771cb?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: shelf-life limits on fresh lines are hard constraints
- Pilot scope: one store region
- delivery schedule coupling with ordering
- Budget: pilot ~€180k, rollout maybe €965k/yr if it works
- Needs to go to their budget committee

### 2026-05-06 · Call w/ Juhani

מקור: https://app.notion.com/p/1e8275a3be2382bca8858106e7bfaa13?pvs=204 · Meeting type: Pilot sync

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €185k, 13 weeks
- Scope: shadow-mode planning on 500 SKUs
- Success = on-time-in-full improvement in shadow mode, zero violations of 'fill rate never below SLA'

### 2026-05-07 · Call w/ Juhani

מקור: https://app.notion.com/p/f71275a3be23822ba37381aacd2cff31?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Blocked ~2 weeks on data export, unblocked now
- wk 16. next: interim results to their VP

### 2026-05-08 · Ardent followup

מקור: https://app.notion.com/p/e91275a3be23835c891581d1172a204d?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - no budget this fy
- Graham open to revisit next year

### 2026-05-10 · Meridian <> Vendora

מקור: https://app.notion.com/p/82c275a3be23837288d6814fdf4eb3bf?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Short call, distracted
- Chiara has gone quiet - may be changing role
- chase in 2 weeks

### 2026-05-22 · Rhona Transport call

מקור: https://app.notion.com/p/c4c275a3be238328b35b01ff71f53b1d?pvs=204 · Meeting type: חסר

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €95k, 16 weeks
- Scope: 3-warehouse cluster
- Success = inventory turns improvement in shadow mode, zero violations of 'every transfer order reversible before dispatch'

### 2026-05-22 · Granfield <> Vendora

מקור: https://app.notion.com/p/d18275a3be238303bc308122b992c0a3?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 12. next: second scenario

### 2026-05-24 · Mosel Fracht

מקור: https://app.notion.com/p/b3e275a3be2383a685330139a76fb2e1?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Shadow policy: 11% lower inventory holding
- wk 4. next: second scenario

### 2026-05-28 · Verdant Creamery

מקור: https://app.notion.com/p/423275a3be2382e88eba016af522ece2?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 16. next: interim results to their VP

### 2026-05-30 · Call w/ Alejandro

מקור: https://app.notion.com/p/1a5275a3be23821b8a870188afcf6524?pvs=204 · Meeting type: Pilot sync

#### Agenda
#### Notes
- Shadow policy: 3% fewer stock-outs
- wk 4. next: second scenario

### 2026-05-30 · GB

מקור: https://app.notion.com/p/e55275a3be238389be0701920e5f6957?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Results mixed (0%)
- Rollout budget not approved

### 2026-06-02 · Call w/ Annika

מקור: https://app.notion.com/p/9d4275a3be23826ab85a01009b31aa35?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - not a priority vs capacity ramp
- Annika open to revisit next year

### 2026-06-05 · Nordahl

מקור: https://app.notion.com/p/628275a3be23837eaafa81c5fcd1ae0b?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Shadow policy: 6% lower inventory holding
- wk 4. next: weekly review with ops

### 2026-06-08 · VC

מקור: https://app.notion.com/p/90f275a3be2383fcb6fa01d2ff2e654e?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Results mixed (3%)
- Rollout budget not approved

### 2026-06-21 · Call w/ Jonas

מקור: https://app.notion.com/p/aa3275a3be238311936881028ff851ed?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 4. next: interim results to their VP

### 2026-06-23 · Mosel Fracht

מקור: https://app.notion.com/p/6bd275a3be2383f2947c81feed545dd6?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 8. next: interim results to their VP

### 2026-06-26 · Pinecrest

מקור: https://app.notion.com/p/42b275a3be238229ad290192e96974ec?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- working-capital target for 2027 with no plan - Vera says this costs them real money
- Setup: new WMS rollout
- multi-warehouse allocation conflicts
- Keen - wants to see the guardrail design
- Next: send one-pager, book scoping w/ Vera's team

### 2026-06-27 · Lucerna

מקור: https://app.notion.com/p/84e275a3be2382dabcf1817f0a2ca66b?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- auto-replenishment switched off because planners don't trust it - Brooke says this costs them real money
- Setup: home-grown scripts on stock reports
- multi-warehouse allocation conflicts
- Polite, not urgent. 'Interesting research'
- Next: send materials, ping in a few weeks

### 2026-06-29 · Tamaro sync

מקור: https://app.notion.com/p/525275a3be238320a26301e26c839d39?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Shadow policy: 9% fewer stock-outs
- wk 8. next: weekly review with ops

### 2026-07-01 · Carreta

מקור: https://app.notion.com/p/deb275a3be2382c3987a01ae9e3ef062?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - couldn't get historic data
- Luca open to revisit next year

### 2026-07-05 · Nordahl

מקור: https://app.notion.com/p/7d3275a3be238393b1ac011e66e718ea?pvs=204 · Meeting type: Pilot sync

#### Agenda
#### Notes
- Guardrail flagged some proposed orders that would've broken a hard constraint - they liked that
- wk 8. next: second scenario

### 2026-07-07 · Tamaro

מקור: https://app.notion.com/p/415275a3be2382e29f6f813451adca47?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Results mixed (1%)
- Rollout budget not approved

### 2026-07-07 · IM

מקור: https://app.notion.com/p/c8e275a3be2382ba8eee0190da087bcb?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- fresh produce stock-outs every weekend - Margaux says this costs them real money
- Setup: in-house ERP + spreadsheet replenishment
- promotions break the heuristics
- Keen - wants a deep dive with their engineers
- Next: send one-pager, book scoping w/ Margaux's team

### 2026-07-10 · RT

מקור: https://app.notion.com/p/8e7275a3be238389bfdb8194b20208d6?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Jonas: budget pressure, rollout scoped down to shadow-mode planning on 500 SKUs
- realistic full value now ~$220k/yr

### 2026-07-10 · TS

מקור: https://app.notion.com/p/c8b275a3be23820186c301b0867d7268?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - went with incumbent ERP/WMS vendor add-on
- Alejandro open to revisit next year

### 2026-07-19 · Nordahl

מקור: https://app.notion.com/p/86f275a3be2382ee96aa019e47980dcd?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Results mixed (1%)
- Rollout budget not approved

### 2026-07-20 · Westra Trading

מקור: https://app.notion.com/p/d38275a3be23835abe84812f34c29af9?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: two-vendor WMS + vendor planning suite
- Pilot scope: shadow-mode planning on 500 SKUs
- they want it in the WMS not as a separate tool
- Budget: pilot ~€135k, rollout maybe €730k/yr if it works

### 2026-07-21 · RT

מקור: https://app.notion.com/p/dd6275a3be2383d1ab798170da646272?pvs=204 · Meeting type: Pilot sync

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 8. next: second scenario

### 2026-07-22 · Nordahl

מקור: https://app.notion.com/p/edc275a3be2383b6890981b628e70aa6?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Lost - building in-house with their data science team
- Juhani open to revisit next year

### 2026-07-22 · Solvik followup

מקור: https://app.notion.com/p/fd1275a3be2382388a160158f54b4502?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Short call, distracted
- still waiting on data access, no reply to last 2 emails
- chase in 2 weeks

### 2026-07-23 · Pinecrest Wholesale <> Vendora

מקור: https://app.notion.com/p/640275a3be238239acfc01dedde28545?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: daily stock-level feeds
- Pilot scope: shadow-mode planning on 500 SKUs
- inventory per SKU per week
- Budget: pilot ~$175k, rollout maybe $800k/yr if it works

### 2026-07-23 · Mosel Fracht

מקור: https://app.notion.com/p/768275a3be2382deabad01f87ab68cfd?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Guardrail flagged some proposed orders that would've broken a hard constraint - they liked that
- wk 12. next: interim results to their VP

### 2026-07-24 · Kavala Markets

מקור: https://app.notion.com/p/555275a3be238242b06a81bef4c25df1?pvs=204 · Meeting type: Follow-up

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- ordering rules nobody fully understands - Jun Hao says this costs them real money
- Setup: forecasting module that is replaceable behind the ordering interface
- store-level daily ordering
- Keen - wants a deep dive with their engineers
- Next: send one-pager, book scoping w/ Jun Hao's team

### 2026-07-26 · Halvard <> Vendora

מקור: https://app.notion.com/p/fe3275a3be2382e0a233017f53cab102?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- fresh produce stock-outs every weekend - Ji-woo says this costs them real money
- Setup: commercial ERP with ~400 custom reorder rules
- want to see the benchmark result extended to fresh categories
- Keen - wants to see the guardrail design
- Next: send one-pager, book scoping w/ Ji-woo's team

### 2026-07-30 · Osprey

מקור: https://app.notion.com/p/3cf275a3be23831eb017019727fced4e?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- fresh produce stock-outs every weekend - Hsiao-Wen says this costs them real money
- Setup: forecasting module that is replaceable behind the ordering interface
- supplier lead times matter
- Keen - wants a deep dive with their engineers
- Next: send one-pager, book scoping w/ Hsiao-Wen's team

### 2026-07-31 · WT

מקור: https://app.notion.com/p/82c275a3be23825e8b1b01fdccb01f56?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: every transfer order reversible before dispatch
- Pilot scope: shadow-mode planning on 500 SKUs
- customer-level fill-rate KPIs
- Budget: pilot ~€135k, rollout maybe €730k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-08-03 · Ilex <> Vendora

מקור: https://app.notion.com/p/ee7275a3be2382f79b33814c56ca050b?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Integration: commercial ERP with ~400 custom reorder rules
- Pilot scope: dairy category
- want to see the benchmark result extended to fresh categories
- Budget: pilot ~€230k, rollout maybe €1.1M/yr if it works

### 2026-08-04 · PW

מקור: https://app.notion.com/p/88d275a3be23829fb3fb813ef8bb0a99?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Data: warehouse cost data
- Pilot scope: shadow-mode planning on 500 SKUs
- inventory per SKU per week
- Budget: pilot ~$175k, rollout maybe $800k/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-08-09 · Call w/ Ji-woo

מקור: https://app.notion.com/p/dc2275a3be2382b3ae0881c1ee0bd0b7?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: commercial ERP with ~400 custom reorder rules
- Pilot scope: one store region
- supplier lead times matter
- Budget: pilot ~$300k, rollout maybe $1.3M/yr if it works

### 2026-08-15 · PW

מקור: https://app.notion.com/p/7a8275a3be2383fda89d813a7e68250f?pvs=204 · Meeting type: Pilot sync

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: $175k, 16 weeks
- Scope: shadow-mode planning on 500 SKUs
- Success = inventory turns improvement in shadow mode, zero violations of 'every transfer order reversible before dispatch'

### 2026-08-18 · Westra Trading <> Vendora

מקור: https://app.notion.com/p/867275a3be2382bf9d3d017640f07ff5?pvs=204 · Meeting type: חסר

#### Agenda
- Kickoff
- Data access
- Success criteria
#### Notes
- Pilot signed: €135k, 10 weeks
- Scope: shadow-mode planning on 500 SKUs
- Success = inventory turns improvement in shadow mode, zero violations of 'fill rate never below SLA'

### 2026-08-19 · Call w/ Margaux

מקור: https://app.notion.com/p/c20275a3be2383bd8a9e8123321fbbfa?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: POS sales history
- Pilot scope: one product family, shadow mode
- delivery schedule coupling with ordering

### 2026-08-20 · Rhona

מקור: https://app.notion.com/p/261275a3be2383adbefe017ca58a9775?pvs=204 · Meeting type: Pilot sync

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 12. next: weekly review with ops

### 2026-08-20 · Halvard

מקור: https://app.notion.com/p/ab6275a3be2383a3bde1810caea42602?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- They want to extend to a second region if pilot works
- Ji-woo's number for full rollout ~€2.2M/yr

### 2026-08-20 · Kavala Markets

מקור: https://app.notion.com/p/af7275a3be23823f94838173354f5f05?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: shelf-life limits on fresh lines are hard constraints
- Pilot scope: one store region
- delivery schedule coupling with ordering
- Budget: pilot ~$200k, rollout maybe $810k/yr if it works

### 2026-08-22 · Mosel Fracht

מקור: https://app.notion.com/p/a4e275a3be23829082fc81f7f58142c8?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Forecast model fit on historic data, held-out error within tolerance
- wk 16. next: weekly review with ops

### 2026-08-23 · Call w/ Ji-woo

מקור: https://app.notion.com/p/f21275a3be2382ebb20b01831ffd86a7?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: 18 months store order history
- Pilot scope: bakery and deli
- supplier lead times matter

### 2026-08-25 · Mosel Fracht

מקור: https://app.notion.com/p/a65275a3be2382bd9f4e81412cb581e1?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Results mixed (3%)
- Rollout budget not approved

### 2026-08-27 · Call w/ Hsiao-Wen

מקור: https://app.notion.com/p/98a275a3be23829f902e0107aa75370a?pvs=204 · Meeting type: Scoping

#### Agenda
#### Notes
- Hard constraint: no order to a supplier outside the approved list
- Pilot scope: bakery and deli
- delivery schedule coupling with ordering
- Budget: pilot ~$185k, rollout maybe $960k/yr if it works

### 2026-08-30 · Kavala call

מקור: https://app.notion.com/p/ae6275a3be2382a4a1648129ac854a97?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Data: POS sales history
- Pilot scope: dairy category
- want to see the benchmark result extended to fresh categories

### 2026-09-04 · IM <> Vendora

מקור: https://app.notion.com/p/8b9275a3be2383ddaac1013340d09e02?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: forecasting module that is replaceable behind the ordering interface
- Pilot scope: one product family, shadow mode
- want to see the benchmark result extended to fresh categories
- Budget: pilot ~€230k, rollout maybe €1.1M/yr if it works
- Needs to go to their budget committee

### 2026-09-09 · Osprey

מקור: https://app.notion.com/p/d76275a3be2382dea71581fd96445589?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Integration: commercial ERP with ~400 custom reorder rules
- Pilot scope: dairy category
- store-level daily ordering

### 2026-09-10 · Halvard

מקור: https://app.notion.com/p/4b2275a3be23833e95ac8182ddeebc9c?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Hard constraint: shelf-life limits on fresh lines are hard constraints
- Pilot scope: dairy category
- delivery schedule coupling with ordering
- Budget: pilot ~$300k, rollout maybe $1.3M/yr if it works
- Verbal yes to paid pilot, SOW being drafted

### 2026-09-11 · WT

מקור: https://app.notion.com/p/622275a3be2383f98c5301c75d72b221?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- Contract NOT signed yet - still with their procurement/legal
- they want to extend pilot ~6 weeks
- pricing not agreed, pushback on annual fee

### תאריך חסר · Coldharbour

מקור: https://app.notion.com/p/09b275a3be238224aeb7813f30635247?pvs=204 · Meeting type: חסר

#### Agenda
#### Notes
- (call on 16/05)
- SIGNED. €580k/yr, 2-yr term
- Rollout one distribution centre first

### תאריך חסר · Westra Trading <> Vendora

מקור: https://app.notion.com/p/7d1275a3be2383a9b94d8138f6cf511a?pvs=204 · Meeting type: חסר

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- (call on 28/06)
- working-capital target for 2027 with no plan - Magdalena says this costs them real money
- Setup: new WMS rollout
- safety stock vs cross-docking
- Keen - wants a deep dive with their engineers
- Next: send one-pager, book scoping w/ Magdalena's team

### תאריך חסר · Coldharbours

מקור: https://app.notion.com/p/dff275a3be238253ae57011349adc7a2?pvs=204 · Meeting type: Pilot sync

#### Agenda
#### Notes
- (call on 13/05)
- Results: 14% fewer expiry write-offs, no constraint violations
- Steering committee: go to commercial
- ACV discussed €580k/yr

### תאריך חסר · Nordahl

מקור: https://app.notion.com/p/e5a275a3be238253b8e40119c8e5e527?pvs=204 · Meeting type: Follow-up

#### Agenda
- Intro Vendora
- Their pain points
#### Notes
- (call on 08/03)
- auto-replenishment switched off because planners don't trust it - Juhani says this costs them real money
- Setup: home-grown scripts on stock reports
- they want it in the WMS not as a separate tool
- Keen - wants the benchmark result on their data
- Next: send one-pager, book scoping w/ Juhani's team


## 38 הערות חברות ב־Airtable

אלו snapshots ותקצירי עבודה; תאריך בתוך סוגריים מרובעים הוא תאריך sync עסקי כפי שנכתב, בעוד Created Date של הרשומה אינו היסטוריית עדכונים.

### Rhona Transport

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/rec5l7sxgdr3MvgNy

Met Jonas at Supply Chain Summit Barcelona 2026 - asked for a demo.

[2026-05-18 sync — Claude] Scoping ongoing since 02 Apr; data: warehouse cost data. Pilot ballpark €95k. ~25-35% pilot intent by 22 Jun.

[2026-06-15 sync — Claude] Pilot live since 22 May. Early results promising. Commercial decision expected ~Aug. ~60% conversion to deployment.

[2026-07-20 sync — Claude] Pilot live since 22 May. Early results promising. Commercial decision expected ~Aug. ~60% conversion to deployment.

[2026-08-17 sync — Claude] Pilot live since 22 May. Early results promising. Commercial decision expected ~Oct. ~60% conversion to deployment.

[2026-09-07 sync — Claude] Pilot live since 22 May. Early results promising. Commercial decision expected ~Oct. ~55% conversion to deployment.

### Verdant Creamery

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recBULaV7LhmfU8iF

[2026-05-18 sync — Claude] Pilot live since 28 Jan. Early results promising. Commercial decision expected ~Jul. ~60% conversion to deployment.

[2026-06-15 sync — Claude] Closed - went with incumbent ERP/WMS vendor add-on.

### Halvard Supermarkets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recD7Z4zX4ghZJfgt

Met Ji-woo at RetailForward West 2026 - keen.

[2026-07-20 sync — Claude] Lead from RetailForward West 2026; follow-up not booked yet. ~5% pilot intent by 13 Sep.

[2026-08-17 sync — Claude] Scoping ongoing since 09 Aug; data: daily stock snapshots. Pilot ballpark $300k. ~25-35% pilot intent by 30 Sep.

### Ardent Wholesale

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recDd1ErKE10A7kKV

Met Graham at Supply Chain Summit Barcelona 2026 - sceptical on guarantee claims.

[2026-05-18 sync — Claude] Closed - no budget this fy.

### Elmar Grocers

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recFZsiGNj0PKiT8t

Tier A. Convenience store chain, forecasting module that is replaceable behind the ordering interface. Pain likely: stock-outs creeping up since new product mix.

### Quorra Supply

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recFyXnjvXGaHfqfx

Met Tiago at Supply Chain Summit Barcelona 2026 - asked for a demo.

[2026-05-18 sync — Claude] Closed - couldn't get historic data.

### Coldharbour Pharma

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recIGgZF0EJepGDd0

[2026-05-18 sync — Claude] Signed 16 May: €580k/yr.

### Bastion Supply

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recKB6ughIAQGhFaz

Met Kavya at Supply Chain Summit Barcelona 2026 - asked for a demo.

### Godavari Supermarkets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recKO3E8uDRnI2HaE

Tier A greenfield. New store format, first stores 2028, announced as fully automated with robotic fulfilment. ERP choice still open - chance to be designed in from day one.

Met Jun Hao at RetailForward Asia 2026 - curious.

### Pinecrest Wholesale

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recKSGp6ag7Fjwyjk

Met Vera at Distribution Ignite 2026 - curious.

[2026-07-20 sync — Claude] Follow-up held 26 Jun with Vera. Working-capital target for 2027 with no plan. Play: get to their ops lead. ~10-15% pilot intent by 08 Sep.

[2026-08-17 sync — Claude] Pilot live since 15 Aug. Early results promising. Commercial decision expected ~Oct. ~55% conversion to deployment.

[2026-09-07 sync — Claude] Pilot live since 15 Aug. Early results promising. Commercial decision expected ~Oct. ~50% conversion to deployment.

### Sobaek Supermarkets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recQp3G3gg9WiC75e

Tier A. Specialty grocer, forecasting module that is replaceable behind the ordering interface. Pain likely: ordering rules nobody fully understands.

Met Hyun-woo at RetailForward Asia 2026 - asked for a demo.

### Nordahl Distribution

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recTysPhTvhhpxZmT

Met Juhani at Supply Chain Summit Barcelona 2026 - asked for a demo.

[2026-05-18 sync — Claude] Pilot live since 06 May. Early results promising. Commercial decision expected ~Jul. ~60% conversion to deployment.

[2026-06-15 sync — Claude] Pilot live since 06 May. Early results promising. Commercial decision expected ~Jul. ~60% conversion to deployment.

[2026-07-20 sync — Claude] Pilot live since 06 May. Early results promising. Commercial decision expected ~Sep. ~50% conversion to deployment.

[2026-08-17 sync — Claude] Closed - building in-house with their data science team.

### Kordis ERP

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recVaKyqjrYfdZ1by

Partner, not customer: their ERP module sits where our forecasts would plug in. Possible channel / OEM route.

### Juniper Vale Markets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recW1BzIaNE1DxARh

Tier A. National supermarket chain, commercial ERP with ~400 custom reorder rules. Pain likely: reorder points hand-tuned per store.

### Corvelle Markets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recWng6FucVe3xigZ

[2026-05-18 sync — Claude] Closed - went with incumbent ERP/WMS vendor add-on.

### Mysig Grossist

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recXJ5vQ3q1zZrl93

Met Astrid at Distribution Ignite 2026 - sceptical on guarantee claims.

[2026-07-20 sync — Claude] Closed - not a priority vs capacity ramp.

### Kavala Markets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recXW8Ku6UScnu2mD

Tier A greenfield. Large-format network, first stores 2027, announced as fully automated with robotic fulfilment. ERP choice still open - chance to be designed in from day one.

Met Jun Hao at RetailForward West 2026 - curious.

[2026-07-20 sync — Claude] Lead from RetailForward West 2026; follow-up not booked yet. ~5% pilot intent by 14 Sep.

[2026-09-07 sync — Claude] Scoping ongoing since 20 Aug; data: daily stock snapshots. Pilot ballpark $200k. ~25% pilot intent by 02 Nov.

### Tamaro Supermarkets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recZMghTb9d0ef0sp

Met Alejandro at RetailForward Seoul 2026 - keen.

[2026-05-18 sync — Claude] Pilot live since 30 Apr. Early results promising. Commercial decision expected ~Jun. ~50% conversion to deployment.

[2026-06-15 sync — Claude] Pilot live since 30 Apr. Early results promising. Commercial decision expected ~Aug. ~60% conversion to deployment.

[2026-07-20 sync — Claude] Closed - went with incumbent ERP/WMS vendor add-on.

### Stocktrace Software

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recZZYqStaR4EOjPb

Partner, not customer: their ERP module sits where our forecasts would plug in. Possible channel / OEM route.

### Puli Fresh Markets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recesd7kesGXMmQmH

Tier C. Regional supermarket chain, in-house ERP + spreadsheet replenishment. Pain likely: reorder points hand-tuned per store.

Met Yi-Hsuan at RetailForward Asia 2026 - asked for a demo.

### Meridian Markets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recfSTf0vqAVQ46kX

Tier A. Regional supermarket chain, commercial ERP with ~400 custom reorder rules. Pain likely: write-offs on short shelf-life lines.

### Wessex Foodstores

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/reciWwbRYOUqSWKxC

Met Felix at RetailForward Asia 2026 - sceptical on guarantee claims.

### Lone Pine Grocers

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recifYQdtGilL7SDz

Tier B. National supermarket chain, forecasting module that is replaceable behind the ordering interface. Pain likely: write-offs on short shelf-life lines.

Met Derek at RetailForward Seoul 2026 - sceptical on guarantee claims.

### Hualien Supermarket Group

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recjU4mP3oqG61fUV

Tier B. Specialty grocer, commercial ERP with ~400 custom reorder rules. Pain likely: write-offs on short shelf-life lines.

### Aldwin Lebensmittel

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recjkUSiRjgNC4F3H

Met Helena at RetailForward Seoul 2026 - keen.

### Granfield Bakeries

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/reckEqTpGi1bunrDj

[2026-05-18 sync — Claude] Pilot live since 21 Feb. Early results promising. Commercial decision expected ~Jul. ~60% conversion to deployment.

[2026-06-15 sync — Claude] Closed - not a priority vs capacity ramp.

### Mosel Fracht

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/reclgJYoM8dAETv7M

Met Felix at Supply Chain Summit Barcelona 2026 - curious.

[2026-05-18 sync — Claude] Pilot live since 24 Apr. Early results promising. Commercial decision expected ~Jun. ~55% conversion to deployment.

[2026-06-15 sync — Claude] Pilot live since 24 Apr. Early results promising. Commercial decision expected ~Jul. ~55% conversion to deployment.

[2026-07-20 sync — Claude] Pilot live since 24 Apr. Early results promising. Commercial decision expected ~Sep. ~60% conversion to deployment.

[2026-08-17 sync — Claude] Pilot live since 24 Apr. Early results promising. Commercial decision expected ~Oct. ~50% conversion to deployment.

[2026-09-07 sync — Claude] Closed - not a priority vs capacity ramp.

### Haneul Mart

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recqJLUaz9vVJ3vv7

Tier A. Regional supermarket chain, in-house ERP + spreadsheet replenishment. Pain likely: stock-outs creeping up since new product mix.

### Jinwen Retail

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recqfue1u3YMnjaqp

Tier B. Specialty grocer, forecasting module that is replaceable behind the ordering interface. Pain likely: write-offs on short shelf-life lines.

### Nanshan Markets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recqiwmeyiYMEVO3Y

Tier C. Convenience store chain, commercial ERP with ~400 custom reorder rules. Pain likely: reorder points hand-tuned per store.

Met Jia-Hao at RetailForward Asia 2026 - asked for a demo.

### Lucerna Wholesale

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recqrCX7H1rp2VIS9

Met Brooke at Distribution Ignite 2026 - curious.

[2026-08-17 sync — Claude] Closed - not a priority vs capacity ramp.

### Tejo Carreta

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recrRYlTRhhA4P7mY

Met Luca at Distribution Ignite 2026 - curious.

[2026-07-20 sync — Claude] Closed - couldn't get historic data.

### Kumano Distribution

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recs0vWDVeO145idC

Met Natsuki at Supply Chain Summit Barcelona 2026 - curious.

### Westra Trading

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recspxjeYxXU3CK6l

Met Magdalena at Distribution Ignite 2026 - sceptical on guarantee claims.

[2026-07-20 sync — Claude] Scoping ongoing since 20 Jul; data: 12 months shipment history. Pilot ballpark €135k. ~25% pilot intent by 23 Aug.

[2026-08-17 sync — Claude] Scoping ongoing since 20 Jul; data: 12 months shipment history. Pilot ballpark €135k. ~25-35% pilot intent by 01 Oct.

[2026-09-07 sync — Claude] Pilot live since 18 Aug. Early results promising. Commercial decision expected ~Oct. ~60% conversion to deployment.

### Osprey Grocers

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/rect6Ma6n13y7bkp5

Tier B. Convenience store chain, in-house ERP + spreadsheet replenishment. Pain likely: stock-outs creeping up since new product mix.

Met Hsiao-Wen at RetailForward West 2026 - curious.

[2026-07-20 sync — Claude] Lead from RetailForward West 2026; follow-up not booked yet. ~5% pilot intent by 25 Aug.

[2026-09-07 sync — Claude] Scoping ongoing since 27 Aug; data: POS sales history. Pilot ballpark $185k. ~30% pilot intent by 14 Nov.

### Kohana Foodhalls

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recwa2Wcnq62kXXW4

Met Hideo at RetailForward Seoul 2026 - keen.

### Red Mesa Grocers

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/recwkGF55H8KLVjRd

Tier B. Convenience store chain, in-house ERP + spreadsheet replenishment. Pain likely: stock-outs creeping up since new product mix.

Met Megan at RetailForward West 2026 - curious.

[2026-07-20 sync — Claude] Lead from RetailForward West 2026; follow-up not booked yet. ~5% pilot intent by 23 Aug.

[2026-08-17 sync — Claude] Closed - not a priority vs capacity ramp.

### Solvik Supermarkets

Airtable: https://airtable.com/appTOQzrJYUrdHRtK/tblMmaTP8Yo1Jh0qs/reczEuZgFu7jy4ThU

Tier A. Regional supermarket chain, forecasting module that is replaceable behind the ordering interface. Pain likely: stock-outs creeping up since new product mix.

Met Tae-yang at RetailForward West 2026 - keen.


## הערות Deals

Osprey pilot (rec7Q5bEBJ7rdBmzr): Champion: Hsiao-Wen
