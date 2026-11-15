// Public demo of the bot dashboard (/demo). Loaded before dashboard.js: it answers the dashboard's API calls
// in the browser with invented conversations, so the real panel can be shown without an account or a server.
// Nothing leaves the page; every person and message below is fictional.
(function () {
  'use strict';
  const NOW = Date.now(), MIN = 60e3, HOUR = 60 * MIN, DAY = 24 * HOUR;
  const iso = ms => new Date(ms).toISOString().replace(/\.\d{3}Z$/, '+00:00');
  const ago = ms => iso(NOW - ms);
  const day = offset => new Date(NOW + offset * DAY).toISOString().slice(0, 10);

  // [id, name, age, bio, matched ago, messages [sender, body, ago], draft, outcomes, plan]
  const PEOPLE = [
    ['d1', 'Julia', 26, 'góry > morze. szukam kogoś na wspólne wypady i dobrą kawę po', 3 * DAY,
      [['them', 'hej! widzę, że też byłeś w Tatrach, która trasa najlepsza?', 26 * HOUR],
       ['you', 'orla perć, ale z perspektywy czasu to było bardziej odważne niż mądre', 25 * HOUR],
       ['them', 'hahah szanuję. ja w tym roku tylko Rysy, ale wschód słońca był nieziemski', 40 * MIN]],
      {status: 'pending', body: 'wschód na Rysach to mocna rzecz. wstawałaś o 2 w nocy czy spałaś w schronisku?'},
      [], {stage: 'rapport', move: 'react_and_follow_up', why: 'Odpisuje szybko i dopytuje. Warto podtrzymać temat gór i dopytać o szczegół z jej wiadomości.', interest: 74, signals: ['zadaje pytania (1)', 'śmieje się', 'odpisuje w ciągu godziny'], exchanges: 2}],
    ['d2', 'Ola', 24, 'architektka, planszówki, za dużo kotów na insta', 6 * DAY,
      [['them', 'cześć, grasz w planszówki czy tylko masz zdjęcie z Catanem dla lansu?', 3 * DAY],
       ['you', 'gram, i przegrywam z godnością. ty jesteś od strategii czy od imprezowych?', 3 * DAY - 20 * MIN],
       ['them', 'strategia, zdecydowanie. Terraformacja Marsa to mój konik', 2 * DAY],
       ['you', 'to musimy kiedyś zagrać. jest fajny bar z planszówkami na Mokotowie', 2 * DAY - 15 * MIN],
       ['them', 'brzmi dobrze! dodaj mnie na insta, łatwiej się umówić: ola.rysuje', 5 * HOUR]],
      {status: 'pending', body: 'dodane! to w czwartek wieczorem? przegrany stawia pierwszą kolejkę'},
      [{kind: 'instagram_shared', details: {handle: 'ola.rysuje'}, ago: 5 * HOUR}],
      {stage: 'logistics', move: 'settle_details', why: 'Sama podała Instagram i zgodziła się na spotkanie. Zostało ustalić dzień i godzinę.', interest: 88, signals: ['podała Instagram', 'zgodziła się na spotkanie', 'zadaje pytania (1)'], exchanges: 4}],
    ['d3', 'Lena', 27, 'kawa, rower, książki. 168 cm', 9 * DAY,
      [['you', 'to co, sprawdzamy tę kawiarnię z sernikiem baskijskim?', 2 * DAY],
       ['them', 'jasne! piątek 19:00 pasuje?', 2 * DAY - 2 * HOUR],
       ['you', 'pasuje, to do zobaczenia w piątek o 19 w Relaksie', 2 * DAY - 2 * HOUR + 10 * MIN],
       ['them', 'super, do zobaczenia 😊', 2 * DAY - HOUR],
       ['you', 'do zobaczenia!', 2 * DAY - 50 * MIN]],
      null,
      [{kind: 'date_confirmed', details: {day: day(2), time: '19:00', place: 'kawiarnia Relaks'}, ago: 2 * DAY - HOUR}],
      {stage: 'date_set', move: 'confirm_lightly', why: 'Termin i miejsce są potwierdzone. Nie dokładamy nowych planów, najwyżej luźne przypomnienie.', interest: 92, signals: ['potwierdziła termin', 'używa emoji'], exchanges: 6}],
    ['d4', 'Nina', 25, 'psycholożka w trakcie, joga, pierogi ruskie to religia', 4 * DAY,
      [['them', 'hej, czy ty na tym zdjęciu naprawdę skaczesz ze spadochronem?', 9 * HOUR],
       ['you', 'tak, i krzyczałem przez całą drogę w dół', 8 * HOUR],
       ['them', 'haha uczciwie. ja bym chyba zemdlała jeszcze w samolocie', 2 * HOUR],
       ['them', 'a co robisz w ten weekend?', 2 * HOUR - 3 * MIN]],
      {status: 'pending', body: 'w sobotę chcę wyskoczyć na kawę na Powiśle. może wpadniesz? obiecuję zero spadochronów'},
      [], {stage: 'invite', move: 'invite', why: 'Sama pyta o weekend i reaguje śmiechem. To dobre okno na lekkie, konkretne zaproszenie.', interest: 81, signals: ['pyta o plany', 'śmieje się', 'pisze dwie wiadomości pod rząd'], exchanges: 3}],
    ['d5', 'Kasia', 28, 'pracuję w IT, w weekendy biegam, w tygodniu udaję, że gotuję', 2 * DAY,
      [['them', 'cześć! jak tam początek tygodnia?', 30 * HOUR],
       ['you', 'spokojnie, trochę pracy, trochę biegania. u ciebie?', 29 * HOUR]],
      null, [], {stage: 'awaiting_answer', move: 'wait', why: 'Ostatnia wiadomość jest Twoja. Nie dopisujemy kolejnej.', interest: 55, signals: ['zadaje pytania (1)'], exchanges: 1}],
    ['d6', 'Zuza', 23, 'studiuję medycynę, więc nie mam czasu, ale mam poczucie humoru', 5 * DAY,
      [['them', 'hej, a ty skąd znasz tę knajpę z ramenem ze zdjęcia?', 20 * HOUR],
       ['you', 'kumpel mnie tam zaciągnął i teraz jestem stałym klientem', 19 * HOUR],
       ['them', 'muszę spróbować. jaki bierzesz?', 25 * MIN]],
      {status: 'pending', body: 'tonkotsu z dodatkowym jajkiem. ty wyglądasz mi na fankę ostrego miso'},
      [], {stage: 'rapport', move: 'react_and_follow_up', why: 'Dopytuje o konkret. Odpowiedz na pytanie i oddaj lekkie pytanie.', interest: 69, signals: ['zadaje pytania (2)'], exchanges: 2}],
    ['d7', 'Maja', 26, 'fotografka, koncerty, podróże pociągiem', 12 * DAY,
      [['you', 'może w środę na wystawę World Press Photo?', 3 * DAY],
       ['them', 'chętnie, ale jutro dam znać, bo nie wiem jeszcze, jak z pracą', 3 * DAY - 3 * HOUR]],
      {status: 'needs_user', body: 'Termin jest otwarty, a Maja miała dać znać. Lepiej, żebyś sam zdecydował, czy przypomnieć, czy poczekać.'},
      [{kind: 'date_suggested', details: {day: 'środa'}, ago: 3 * DAY - 3 * HOUR}],
      {stage: 'logistics', move: 'keep_it_light', why: 'Zgodziła się wstępnie, ale nie potwierdziła terminu. Luźno, bez naciskania.', interest: 63, signals: ['zgodziła się wstępnie'], exchanges: 5}],
    ['d8', 'Wiktoria', 29, 'prawniczka, tenis, dobre wino', 1 * DAY,
      [['them', 'hej, grasz w tenisa czy rakieta na zdjęciu to rekwizyt?', 15 * HOUR],
       ['you', 'gram, ale mój bekhend to wciąż projekt w budowie', 14 * HOUR],
       ['them', 'mogę dać kilka lekcji 😉', 4 * HOUR]],
      {status: 'sent_auto'}, [], null],
    ['d9', 'Ania', 25, 'nowa w Warszawie, szukam ulubionej piekarni', 2 * HOUR, [], null, [],
      {stage: 'opening', move: 'opener_by_owner', why: 'Nowe dopasowanie. Pierwsza wiadomość nawiązuje do bio: nowa w mieście, szuka piekarni.', interest: 50, signals: [], exchanges: 0}],
    ['d10', 'Natalia', 27, 'weterynarz, dwa psy, zero cierpliwości do small talku', 5 * HOUR, [], null, [],
      {stage: 'opening', move: 'opener_by_owner', why: 'Nowe dopasowanie. Bio zachęca do konkretu, bez small talku.', interest: 50, signals: [], exchanges: 0}],
  ];
  // d8 shows autopilot at work: the bot's answer is already sent.
  PEOPLE[7][5].push(['you', 'trzymam za słowo. tylko ostrzegam, że przegrywam z klasą', 3 * HOUR + 58 * MIN]);
  PEOPLE[7][8] = {stage: 'invite', move: 'invite', why: 'Sama zaproponowała wspólną grę. Zaproszenie wyszło od niej, warto je skonkretyzować.', interest: 84, signals: ['proponuje spotkanie', 'puszcza oko'], exchanges: 3};

  const STATE_REASON = {needs_reply: 'Ostatnia wiadomość pochodzi od drugiej osoby.', waiting: 'Ostatnia wiadomość pochodzi od użytkownika.',
    new_match: 'Dopasowanie widoczne, ale bez wiadomości.', paused: 'Użytkownik wstrzymał obsługę.',
    archived: 'Archiwizacja przez użytkownika, nie stan konta na platformie.'};
  const STAGE_LABEL = {opening: 'Otwarcie', rapport: 'Budowanie', invite: 'Okno na zaproszenie', awaiting_answer: 'Czeka na odpowiedź',
    logistics: 'Ustalanie spotkania', date_set: 'Spotkanie ustalone'};
  const MOVE_LABEL = {opener_by_owner: 'Napisz pierwszą wiadomość sam', react_and_follow_up: 'Zareaguj i dopytaj',
    invite: 'Zaproponuj spotkanie', settle_details: 'Ustal dzień, godzinę i miejsce', confirm_lightly: 'Potwierdź luźno, bez nowych planów',
    keep_it_light: 'Luźno, bez naciskania', wait: 'Poczekaj na jej odpowiedź'};
  const OUTCOME_BODY = {date_confirmed: 'Randka potwierdzona. Sprawdź termin i miejsce.', instagram_shared: 'Podała Instagram.',
    date_suggested: 'Propozycja spotkania czeka na potwierdzenie.'};

  const threads = [], messages = {}, drafts = [], notifications = [], outcomeDetails = {}, memory = {}, activity = [];
  let draftId = 1, noteId = 1, actId = 1;
  const sentCount = {auto: 23, manual: 41};  // history before the conversations shown here
  for (const [id, name, age, bio, matched, msgs, draft, outs, plan] of PEOPLE) {
    messages[id] = msgs.map(([sender, body, when], i) => ({id: id + '-' + (i + 1), thread_id: id, sender, body, created_at: ago(when), synced_at: ago(Math.max(0, when - MIN))}));
    const last = messages[id][messages[id].length - 1];
    if (draft && last) {
      if (draft.status === 'sent_auto') {
        activity.push({id: actId++, ts: last.created_at, thread_id: id, event: 'Autopilot wysłał odpowiedź', detail: ''});
      } else {
        drafts.push({id: draftId++, thread_id: id, anchor_message_id: last.id, body: draft.body, status: draft.status,
          generator: 'llm', created_at: iso(Date.parse(last.created_at) + 40e3), display_name: name});
      }
    }
    outcomeDetails[id] = outs.map(o => ({kind: o.kind, fingerprint: id + o.kind, body: OUTCOME_BODY[o.kind], evidence: [last && last.id], details: o.details}));
    for (const o of outs) notifications.push({id: noteId++, thread_id: id, kind: o.kind, fingerprint: id + o.kind, body: OUTCOME_BODY[o.kind], created_at: ago(o.ago), display_name: name});
    memory[id] = msgs.filter(m => m[0] === 'them').slice(-2).map((m, i) => ({thread_id: id, source_id: id + '-' + i, kind: m[1].includes('?') ? 'question_or_suggestion' : 'observation', value: m[1], status: 'explicit_observation', confidence: 'explicit'}));
    threads.push({id, display_name: name, user_paused: 0, user_archived: 0, source_visibility: 'available', source_seen: 1, platform: 'tinder',
      connection_id: 'tinder:demo', chat_id: null, outcomes: outs.map(o => o.kind), automatic_sending: id === 'd8',
      profile: {age, bio, photos: [], photos_full: [], matched_at: ago(matched), last_activity: last ? last.created_at : ago(matched)},
      matched_at: ago(matched), plan: plan && {...plan, stage_label: STAGE_LABEL[plan.stage], move_label: MOVE_LABEL[plan.move], goal: 'date', allow_instagram: true}});
  }
  const settings = {mode: 'supervised', paused: false, language: 'auto',
    style: 'krótko, zwykle około 40 znaków, od małej litery, lekki humor, bez emoji, pytanie tylko gdy naturalne',
    profile: {imię: 'Michał', wiek: '28', miasto: 'Warszawa', praca: 'grafik', pasje: 'góry, bieganie, planszówki, ramen'},
    feedback: [], email: true, retention_days: 365, goal: 'date', allow_instagram: true, pace: 'normal',
    availability: 'zwykle wieczory w tygodniu, w weekend elastycznie',
    date_ideas: ['kawa albo matcha na mieście', 'spacer z kawą na wynos', 'planszówki w barze', 'wystawa albo targi']};

  const conn = {id: 'tinder:demo', enabled: true, unofficial: true, auto_send: true, bio_mode: true, bio_disclosure: true,
    error: null, last_sync: null, next_poll: 0, blocked_until: 0, failures: 0};
  const autopilot = () => conn.auto_send && conn.bio_mode && conn.bio_disclosure;

  function project(t) {
    const h = messages[t.id], last = h[h.length - 1];
    const own = drafts.filter(d => d.thread_id === t.id && (d.status === 'pending' || d.status === 'needs_user'));
    const current = !!(last && own.some(d => d.anchor_message_id === last.id && d.status === 'pending'));
    const state = t.user_archived ? 'archived' : t.user_paused ? 'paused' : !last ? 'new_match' : last.sender === 'them' ? 'needs_reply' : 'waiting';
    const next = current && state === 'needs_reply' ? 'review_draft' : state === 'needs_reply' ? 'prepare_draft' : state === 'new_match' ? 'inspect_profile' : 'no_action';
    let plan = t.plan;
    if (state === 'waiting' && plan && plan.stage !== 'date_set') plan = {...plan, stage: 'awaiting_answer', stage_label: STAGE_LABEL.awaiting_answer, move: 'wait', move_label: MOVE_LABEL.wait, why: 'Ostatnia wiadomość jest Twoja. Nie dopisujemy kolejnej.'};
    return {...t, plan, state, state_reason: STATE_REASON[state], next_action: next, message_count: h.length,
      latest_message: last ? last.body : null, latest_sender: last ? last.sender : null, latest_message_id: last ? last.id : null,
      pending_draft_count: own.filter(d => d.status === 'pending').length, has_current_draft: current,
      sort_at: last ? last.created_at : t.profile.matched_at, automatic_sending: autopilot() && !t.user_paused};
  }

  function stats(rows) {
    const all = Object.values(messages).flat();
    const you = all.filter(m => m.sender === 'you').length, them = all.filter(m => m.sender === 'them').length;
    const byState = {};
    rows.forEach(t => { byState[t.state] = (byState[t.state] || 0) + 1; });
    const perDay = [];
    for (let i = 6; i >= 0; i--) {
      const d = day(-i), on = all.filter(m => m.created_at.slice(0, 10) === d);
      perDay.push({day: d, you: on.filter(m => m.sender === 'you').length + [3, 5, 2, 6, 4, 0, 0][6 - i], them: on.filter(m => m.sender === 'them').length + [4, 6, 3, 7, 5, 0, 0][6 - i]});
    }
    const outs = {};
    Object.values(outcomeDetails).flat().forEach(o => { outs[o.kind] = (outs[o.kind] || 0) + 1; });
    const two = rows.filter(t => messages[t.id].some(m => m.sender === 'them') && messages[t.id].some(m => m.sender === 'you')).length;
    return {funnel: {matches: rows.length, conversations: rows.filter(t => t.message_count).length, invite_window: rows.filter(t => t.plan && t.plan.stage === 'invite').length,
        invited: 4, agreed: 3, confirmed: outs.date_confirmed || 0, instagram: outs.instagram_shared || 0},
      with_photos: 0, matches: rows.length, by_state: byState, messages_you: you, messages_them: them, conversations_two_way: two,
      we_wrote: rows.filter(t => messages[t.id].some(m => m.sender === 'you')).length,
      they_replied: rows.filter(t => messages[t.id].some(m => m.sender === 'them')).length,
      drafts: drafts.reduce((a, d) => (a[d.status] = (a[d.status] || 0) + 1, a), {}),
      actions: [{status: 'sent', automatic: 1, n: sentCount.auto}, {status: 'sent', automatic: 0, n: sentCount.manual}], outcomes: outs, per_day: perDay,
      tinder_requests: {minute: 1, hour: 18}};
  }

  function state() {
    const rows = threads.map(project);
    return {threads: rows, messages, drafts, notifications, llm_enabled: true,
      worker: {running: true, last_tick: iso(Date.now() - 20e3), error: null}, settings, grants: [], memory, outcome_details: outcomeDetails,
      activity: activity.slice().reverse(), actions: [], connections: [{id: 'tinder:demo', enabled: 1, can_reply: 1}],
      tinder: {configured: true, enabled: true, unofficial: true, token_source: 'vault', token_fingerprint: 'a41f9c', vault_ready: true,
        connections: [{...conn, last_sync: iso(Date.now() - 2 * MIN)}]},
      account_url: '', stats: stats(rows), outbox: [], metrics: []};
  }

  const OPENERS = {d9: 'cześć! jako lokals polecam Charlotte na Placu Zbawiciela. ale chętnie sprawdzę konkurencję razem z tobą',
    d10: 'konkret na start: pies czy kot, kto wygrywa w twoim domu?'};
  const ALTERNATIVES = ['jasne, chętnie. masz jakieś ulubione miejsce?', 'brzmi jak plan. to kiedy ci pasuje?', 'haha, dobra, przekonałaś mnie'];

  function reply(body, status) {
    return Promise.resolve(new Response(JSON.stringify(body), {status: status || 200, headers: {'Content-Type': 'application/json'}}));
  }

  function send(threadId, body) {
    const h = messages[threadId];
    h.push({id: threadId + '-' + (h.length + 1), thread_id: threadId, sender: 'you', body, created_at: iso(Date.now()), synced_at: iso(Date.now())});
    sentCount.manual++;
    activity.push({id: actId++, ts: iso(Date.now()), thread_id: threadId, event: 'Wysłano po Twoim zatwierdzeniu', detail: ''});
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const path = url.pathname, method = ((init && init.method) || 'GET').toUpperCase();
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) return realFetch(input, init);
    let payload = {};
    try { payload = init && init.body ? JSON.parse(init.body) : {}; } catch (e) { payload = {}; }
    let m;
    if (path === '/api/state') return reply(state());
    if (path === '/api/style') return reply({corpus_pairs: 592, corpus_pl: 496, own_pairs: 38,
      stats: {based_on: 'own', samples: 38, median_chars: 41, lowercase_start_pct: 95, question_pct: 38, emoji_pct: 3, laugh_pct: 11},
      suggested_style: settings.style});
    if (path === '/auth/logout') { location.href = '/'; return reply({ok: true}); }
    if ((m = path.match(/^\/api\/drafts\/(\d+)\/(approve|reject)$/))) {
      const d = drafts.find(x => x.id === +m[1]);
      if (!d) return reply({detail: 'Szkic nie istnieje.'}, 404);
      if (m[2] === 'approve') { send(d.thread_id, payload.body || d.body); d.status = 'sent'; } else d.status = 'rejected';
      return reply({ok: true});
    }
    if ((m = path.match(/^\/api\/threads\/([^/]+)\/regenerate$/))) {
      const id = decodeURIComponent(m[1]), last = messages[id] && messages[id][messages[id].length - 1];
      drafts.filter(d => d.thread_id === id && d.status === 'pending').forEach(d => { d.status = 'superseded'; });
      const prev = drafts.filter(d => d.thread_id === id).length;
      const body = !last ? OPENERS[id] || 'cześć! co dziś dobrego?' : ALTERNATIVES[prev % ALTERNATIVES.length];
      const t = threads.find(x => x.id === id);
      drafts.push({id: draftId++, thread_id: id, anchor_message_id: last ? last.id : null, body, status: 'pending', generator: 'llm', created_at: iso(Date.now()), display_name: t ? t.display_name : ''});
      return reply({ok: true});
    }
    if ((m = path.match(/^\/api\/threads\/([^/]+)\/flags$/))) {
      const t = threads.find(x => x.id === decodeURIComponent(m[1]));
      if (t && 'paused' in payload) t.user_paused = payload.paused ? 1 : 0;
      if (t && 'archived' in payload) t.user_archived = payload.archived ? 1 : 0;
      return reply({ok: true});
    }
    if (/^\/api\/tinder\/connections\/[^/]+\/automation$/.test(path)) {
      if ('enabled' in payload) conn.auto_send = !!payload.enabled;
      if ('bio_mode' in payload) conn.bio_mode = !!payload.bio_mode;
      return reply({ok: true, automatic_sending: conn.auto_send, bio_mode: conn.bio_mode});
    }
    if (path === '/api/settings' && method === 'PUT') { Object.assign(settings, payload); return reply(settings); }
    return reply({ok: true, demo: true});
  };

  // New matches get an opener draft straight away so the demo shows one without a click.
  for (const id of Object.keys(OPENERS)) {
    const t = threads.find(x => x.id === id);
    drafts.push({id: draftId++, thread_id: id, anchor_message_id: null, body: OPENERS[id], status: 'pending', generator: 'llm', created_at: ago(HOUR), display_name: t.display_name});
  }
})();
