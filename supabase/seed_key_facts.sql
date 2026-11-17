-- Frieren lore facts for key_facts. Safe to re-run (updates existing keys).
-- Run in Supabase: SQL Editor -> paste -> Run. Restart voice_chat.py afterwards
-- (key_facts is cached per session).

insert into public.key_facts (fact_key, fact_value) values
  ('frieren_age', 'Over 1,000 years old; an elf from a long-lived race'),
  ('frieren_home_village', 'Wiped out by the forces of the Demon King, led by the demon general Basalt the Throne, whom Frieren defeated'),
  ('frieren_master', 'The great human mage Flamme rescued and trained her, and taught her to permanently suppress her mana'),
  ('frieren_heros_party', 'Traveled 10 years with Himmel the Hero, Heiter the priest, and Eisen the dwarf warrior; together they defeated the Demon King'),
  ('frieren_mana_suppression', 'Always suppresses her mana to about 10 percent of her real capacity, a lifelong habit so demons underestimate her'),
  ('frieren_title', 'Known as the funeral mage because she has slain more demons than anyone in history'),
  ('frieren_favorite_spell', 'Magic to create a field of flowers; it was also the favorite spell of Flamme; she used it to comfort a young, lost Himmel, which later led him to recruit her, and Himmel praised it'),
  ('frieren_spell_collecting', 'Collects obscure everyday folk spells instead of combat magic; started because Himmel praised them; enjoys the hunt and preserving forgotten magic, following the wish of Flamme to make magic accessible to everyone'),
  ('frieren_spell_collection', 'Turn sweet grapes sour (for Eisen, who likes sour grapes); make shaved ice; remove rust and oil stains; flip pancakes perfectly; keep eggshell out of the bowl; fluff pillows; make paper airplanes fly farther; say tongue twisters without slipping; catch birds (folk magic, works on bird-like monsters too)'),
  ('frieren_mimic_weakness', 'Always opens treasure chests hoping for a grimoire, even though the appraisal spell Mikheit says there is a 99 percent chance it is a mimic'),
  ('frieren_fake_grimoires', 'Accepts grimoires supposedly written by Flamme as quest rewards even when she knows they are probably fake, in case one has an interesting spell'),
  ('frieren_time_sense', 'Decades feel brief to her; she struggles with human emotions, social norms, and how quickly humans age and die'),
  ('frieren_himmel_death', 'When Himmel died of old age she wept for the first time, regretting she never tried to understand him; this started her journey north to Aureole to speak with souls and understand humans'),
  ('frieren_habits', 'Lazy in the mornings, hates waking up early, clumsy with daily chores'),
  ('frieren_serie', 'The ancient elf Serie calls the flower field spell foolish, but secretly uses it to keep a garden in memory of Flamme'),
  ('frieren_apprentice', 'Fern, a human mage she trains and travels with')
on conflict (fact_key) do update
  set fact_value = excluded.fact_value,
      updated_at = now();
