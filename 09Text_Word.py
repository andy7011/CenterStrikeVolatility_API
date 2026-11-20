# -*- coding: utf-8 -*-
"""
Генератор Word-документа с описанием работы 09MyQuoter.py.
Запуск:  python make_quoter_doc.py
Результат: 09MyQuoter_Описание.docx
"""
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def set_style_font(style, name='Times New Roman', size=11, bold=False, color=None):
    style.font.name = name
    style.font.size = Pt(size)
    style.font.bold = bold
    if color:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    rfonts.set(qn('w:ascii'), name)
    rfonts.set(qn('w:hAnsi'), name)
    rfonts.set(qn('w:cs'), name)


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = 'Times New Roman'
        run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    return h


def add_para(doc, text, bold=False, italic=False, size=11, align=None, space_after=6):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = 'Times New Roman'
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(text, style='List Bullet' if level == 0 else 'List Bullet 2')
    for run in p.runs:
        run.font.name = 'Times New Roman'
        run.font.size = Pt(11)
    return p


def add_numbered(doc, text):
    p = doc.add_paragraph(text, style='List Number')
    for run in p.runs:
        run.font.name = 'Times New Roman'
        run.font.size = Pt(11)
    return p


def add_code_block(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = 'Consolas'
    run.font.size = Pt(9)
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(4)
    # лёгкая заливка
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), 'F2F2F2')
    pPr.append(shd)
    return p


def build_document():
    doc = Document()

    # Базовые стили
    set_style_font(doc.styles['Normal'], size=11)
    for lvl in range(1, 4):
        try:
            set_style_font(doc.styles[f'Heading {lvl}'], size=14 - lvl, bold=True)
        except KeyError:
            pass

    # Поля страницы
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(1.5)

    # ================= ТИТУЛ =================
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run('ОПИСАНИЕ ПРОГРАММЫ КОТИРОВЩИКА\n09MyQuoter.py')
    r.font.name = 'Times New Roman'
    r.font.size = Pt(20)
    r.bold = True
    r.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run('Автоматизированный котировщик опционной пары (Opener)\n'
                    'на FinamPy + FinLabPy + AlorPy')
    r.font.name = 'Times New Roman'
    r.font.size = Pt(12)
    r.italic = True

    doc.add_paragraph()

    # ================= 1. АННОТАЦИЯ =================
    add_heading(doc, '1. Краткая аннотация назначения программы', level=1)

    add_para(doc,
             '09MyQuoter.py — автоматизированный котировщик опционной пары (Opener) '
             'на срочном рынке MOEX. Программа одновременно котирует две ноги '
             '(опцион на продажу и опцион на покупку) лимитными заявками, цены '
             'которых рассчитываются в единицах подразумеваемой волатильности (IV). '
             'Прибыль пары фиксируется по построению: каждая нога котируется с '
             'профитом (в п.п. IV) относительно противоположной стороны стакана '
             'другой ноги, а встречная заявка выставляется по sec.target — '
             'встречной стороне стакана другой ноги, где предложение заведомо '
             'существует, поэтому вторая сделка исполняется мгновенно.')

    add_para(doc, 'Программа опирается на следующие компоненты:', bold=True)
    add_bullet(doc, 'FinamPy — рыночные данные (котировки, заявки, сделки, портфель) '
                    'и выставление/снятие лимитных заявок.')
    add_bullet(doc, 'AlorPy — справочные данные по опционам (страйк, тип, экспирация, '
                    'теоретическая цена, волатильность).')
    add_bullet(doc, 'FinLabPy.Schedule.MOEX — расписание торгов срочного рынка.')
    add_bullet(doc, 'moex_api — данные MOEX ISS (доска опционов, экспирации).')

    add_para(doc,
             'Поддержаны частичные исполнения, реквот вслед за рынком, три режима '
             'торговли (Open / Close / Auto), предустановка переворота по реальной '
             'Difference position, поджатие таргет-цен в Auto, звуковые сигналы, '
             'светодиодная индикация состояния и текстовая панель предрасчёта. '
             'Графический интерфейс — tkinter. Расчёт цен опционов — Блэк–Шоулз, '
             'расчёт IV по цене — метод Ньютона (общий солвер с ветвлениями для '
             'call/put).')

    # ================= 2. ЛОГИКА ИСПОЛНЕНИЯ =================
    add_heading(doc, '2. Полное описание последовательности логики исполнения '
                     'с момента запуска', level=1)

    add_heading(doc, '2.1. Этап инициализации модуля (до создания GUI)', level=2)
    add_numbered(doc, 'Защита памяти OpenBLAS/OpenMP: переменные окружения '
                      'OPENBLAS_NUM_THREADS=1 и OMP_NUM_THREADS=1 устанавливаются '
                      'через os.environ.setdefault ДО импорта numpy/pandas/scipy. '
                      'Иначе каждый процесс numpy резервирует буфер под все '
                      'логические ядра (~32 МБ на ядро), и при запуске нескольких '
                      'экземпляров котировщика очередной падает с ошибкой '
                      'аллокации памяти.')
    add_numbered(doc, 'Настройка логирования (файл Quoter.log), определение имён: '
                      'filename — имя файла без расширения (используется в '
                      'client_order_id и для распознавания «своих» заявок в '
                      'потоке), file_type — \'Quoter\'.')
    add_numbered(doc, 'Инициализация глобального состояния:')
    add_bullet(doc, 'данные: dataname_sell / dataname_buy (опционы ног), '
                    'subscriptions_dict (активные подписки Финам), options_data '
                    '(справка опционов от Алора), new_quotes / order_dict / '
                    'trade_dict (потоки Финам);', level=1)
    add_bullet(doc, 'параметры (меняются на ходу из GUI): expected_profit_open / '
                    '_close (профит режимов, п.п. IV), select_profit (Sel.profit '
                    'для предустановки переворота), lot_count (число циклов), '
                    'basket_size, timeout, indent;', level=1)
    add_bullet(doc, 'флаги источников профита: theor_flag_open/_close, '
                    'spread_flag_open/_close (галки Th/Sp двух наборов) и их '
                    'активные копии theor_flag / spread_flag;', level=1)
    add_bullet(doc, 'состояния Diff-показателей: diff_theor_current, '
                    'diff_spread_current, diff_spread_last_valid, '
                    'diff_spread_frozen;', level=1)
    add_bullet(doc, 'режим: radio_mode (\'Open\'/\'Close\'/\'Auto\'), applied_mode '
                    '(фактически применённый движком режим, None = Waiting/не '
                    'применялся), legs_swapped (перестановка ног для Close);', level=1)
    add_bullet(doc, 'движок: running, trade_counter (счётчик исполненных пар), '
                    'engine, msg_queue (очередь сообщений из торгового потока в '
                    'GUI-поток).', level=1)
    add_numbered(doc, 'Уникальные client_order_id (next_client_order_id): имя файла '
                      '(до 10 символов) + младшие 32 бита времени в мс (8 hex) + '
                      'счётчик (2 цифры) — итог не длиннее 20 символов (ограничение '
                      'Финам). Префикс по имени файла используется, чтобы отличать '
                      'СВОИ заявки от чужих в order_dict.')
    add_numbered(doc, 'Подготовка каталога CSV сделок: '
                      'data/Finam/Finam_Stream_Trades_ALL.csv — история сделок '
                      'ведётся ВНЕШНЕЙ программой; котировщик только читает её и '
                      'дополняет сделками из потока (кэш _trades_df_cache + '
                      '_stream_trades).')

    add_heading(doc, '2.2. Этап модульного уровня (выполняется при импорте файла)', level=2)
    add_numbered(doc, 'schedule = Futures() — расписание торгов срочного рынка.')
    add_numbered(doc, 'fp_provider = FinamPy(), ap_provider = AlorPy() — подключения.')
    add_numbered(doc, 'Подписки на события Финам: on_quote -> _on_new_quotes, '
                      'on_order -> _on_order, on_trade -> _on_trade.')
    add_numbered(doc, 'Запуск потоков: subscribe_orders_thread (стрим заявок), '
                      'subscribe_trades_thread (стрим сделок), '
                      'subscribe_account_thread (портфель; данные в _account_data[0]: '
                      'позиции, кэш, ГО, нереализованный профит).')
    add_numbered(doc, 'refresh_trades() — первичное чтение CSV в кэш.')
    add_numbered(doc, 'sleep(5) — ожидание установления подключений.')

    add_heading(doc, '2.3. Запуск GUI', level=2)
    add_para(doc, 'if __name__ == \'__main__\': app = App(); app_instance = app; '
                  'app.root.mainloop().')
    add_para(doc,
             'App — единственный объект tkinter. Все обращения из торгового потока '
             'к GUI идут ТОЛЬКО через msg_queue (типы сообщений: \'msg\', \'led\', '
             '\'status\', \'panel\', \'counter\', \'profit\', \'mode\') — tkinter '
             'не потокобезопасен.')
    add_para(doc, 'Три таймера GUI (root.after):', bold=True)
    add_bullet(doc, '_poll_messages, каждые 100 мс — выкачивает msg_queue: '
                    'сообщения в лог, светодиод, статус, панель, счётчик, значение '
                    'Profit, метка режима;')
    add_bullet(doc, '_schedule_preview, каждые 2000 мс — предрасчёт preview_targets '
                    'и опрос сигнала Auto (check_auto_signal) при запущенном '
                    'движке; при остановленном — предрасчёт обновляет '
                    'Diff.theor/Diff.spread в GUI;')
    add_bullet(doc, '_refresh_csv, каждые TRADES_REFRESH_MS (15 с) — перечитывание '
                    'CSV сделок.')

    add_heading(doc, '2.4. Выбор инструментов (колбэки GUI)', level=2)
    add_bullet(doc, 'on_base_asset_change: смена базового актива (например RIZ6) -> '
                    'получение списка экспираций (get_option_expirations), затем '
                    'доски опционов серии (get_option_board из moex_api): '
                    'заполняются sell_tickers_call / sell_tickers_put, для каждого '
                    'тикера тянется справка Алора (get_option_data_alor) в '
                    'options_data: ticker, strikePrice, optionSide, endExpiration, '
                    'minstep, decimals, theorPrice, volatility, lot_size.')
    add_bullet(doc, 'on_expiration_date_change: смена экспирации — перезагрузка доски.')
    add_bullet(doc, 'on_instrument_changed: смена любого инструмента ноги — сброс '
                    'счётчика исполненных пар (новая торговая задача), обновление '
                    'подписок и надписей.')
    add_bullet(doc, 'update_option_pos_labels: подписи «Опцион продажи/покупки» с '
                    'текущей позицией (positions_quantity по портфелю из стрима).')

    add_heading(doc, '2.5. Запуск движка', level=2)
    add_para(doc,
             'start_quoter: синхронизация активных флагов (toggle_theor по обоим '
             'наборам), применение режима (set_mode), создание '
             'QuoterEngine(build_legs()) и запуск потока engine.start(). '
             'stop_quoter: running=False — циклы движка завершаются, cleanup '
             'снимает активные заявки.')

    add_heading(doc, '2.6. Торговый движок QuoterEngine.run() — внешний цикл', level=2)
    add_para(doc,
             'run() НЕ завершается при уходе в Waiting и при исчерпании циклов в '
             'Auto — он ждёт новую торговую задачу (это устраняет прежнюю '
             'деградацию «серый светодиод без заявок»).')
    add_para(doc, 'Последовательность каждой итерации:', bold=True)
    add_numbered(doc, 'auto_waiting() истинно (Auto, обе величины в промежуточной '
                      'зоне) -> wait_signal(): ожидание сработки сигнала.')
    add_numbered(doc, 'Auto, сигнал сработал, но GUI ещё не применил режим '
                      '(applied_mode is None, опрос GUI раз в 2 с) -> '
                      'refresh_signal_values() + sleep(0.2): торговать ногами '
                      'прошлого режима нельзя.')
    add_numbered(doc, 'counter >= lot_count: вне Auto — break (задача исполнена); '
                      'в Auto — idle_auto(): ожидание смены сигнала/числа циклов.')
    add_numbered(doc, 'Иначе run_pair():')
    add_bullet(doc, 'сброс состояния ног; сброс last_pair_profit/last_pair_mode;', level=1)
    add_bullet(doc, 'цикл фазы 1: auto_waiting() -> cleanup + wait_signal, return '
                    'False; вне сессии (session_active) -> cleanup, пауза timeout, '
                    'ожидание; compute_targets() -> если расчёт удался: emit_panel '
                    '(панель), сохранение last_pair_profit (Diff.select) и '
                    'last_pair_mode, maintain_leg(\'sell\') и maintain_leg(\'buy\') '
                    '— постановка/реквот заявок с учётом indent;', level=1)
    add_bullet(doc, 'БЫСТРЫЙ опрос исполнений с шагом poll_step = 0.1 с внутри '
                    'интервала timeout (переквот — раз в timeout, обнаружение '
                    'сделки — каждые 0.1 с, чтобы встречная заявка ушла в стакан, '
                    'пока встречное предложение ещё стоит в книге): обе ноги '
                    'исполнены -> return True; одна исполнена -> run_balance(qty) '
                    '(фаза 2);', level=1)
    add_bullet(doc, 'фаза 2 run_balance: встречная заявка на разницу исполненных '
                    'лотов по sec.target (покупка по ask встречной ноги, продажа по '
                    'bid) с переквотом вслед за стаканом; учёт pending (остатка уже '
                    'стоящей заявки) не позволяет дублировать объём; приём '
                    '«потерянной» заявки; завершение, когда обе ноги исполнены.', level=1)
    add_numbered(doc, 'done=True: counter += 1, обновление счётчика в GUI, сообщение '
                      '«Пара N из M исполнена», звук play_pair_signal.')
    add_numbered(doc, 'ПОДЖАТИЕ таргет-цен (только Auto): '
                      'tighten_auto_profit(last_pair_profit, last_pair_mode) — '
                      'Profit open опускается до фактического Profit сделки, если '
                      'текущий выше; Profit close поднимается, если ниже. Так '
                      'следующая пара котируется по лучшим ценам. Результат '
                      'публикуется в GUI (\'profit\').')
    add_numbered(doc, 'sleep(timeout) — пауза между парами; следующая итерация '
                      'внешнего цикла.')
    add_numbered(doc, 'finally: finish() — cleanup + светодиод серый + статус Stopped.')

    add_heading(doc, '2.7. Расчётное ядро — compute_targets', level=2)
    add_bullet(doc, 'm_sell/m_buy = leg_market(…) — (ask, bid, ask_iv, bid_iv, '
                    'theor_iv) обеих ног; при отсутствии котировок (нет любой '
                    'стороны) — None, итерация пропускается.')
    add_bullet(doc, 'off_sell/off_buy = initial_offset(…): оффсеты в п.п. IV по '
                    'правилу выбора effective_profit (см. раздел 3).')
    add_bullet(doc, 'tiv_sell = ask_iv_buy + off_sell (продажа котируется от ask '
                    'покупаемой ноги), tiv_buy = bid_iv_sell + off_buy (покупка — '
                    'от bid продаваемой).')
    add_bullet(doc, 'sec_target_sell = ask_buy; sec_target_buy = bid_sell — '
                    'встречные цены фазы 2.')
    add_bullet(doc, 'diff_theor = diff_iv(theor_iv_sell, theor_iv_buy, …) — из IV '
                    '«дальней» ноги (больше страйк; при равных — старше серия) '
                    'вычитается IV «ближней»; записывается в diff_theor_current '
                    'для сигнала Auto.')
    add_bullet(doc, 'diff_spread, frozen = update_diff_spread(m_sell, m_buy, '
                    'self.legs) — разница IV середин спреда с детекцией '
                    '«заражения» (своя живая заявка на best ask/bid ноги): при '
                    'заражении значение невалидно, отдаётся последнее валидное '
                    '(заморозка).')
    add_bullet(doc, 'diff_select = effective_profit(diff_theor, diff_spread) — '
                    'реально применяемый профит.')
    add_bullet(doc, 'tp_sell/tp_buy = round_step(option_price(S, tiv/100, K, T, r, '
                    'opt_type)) — целевые ЦЕНЫ из целевых IV по Блэку–Шоулзу с '
                    'округлением к шагу цены.')

    add_heading(doc, '2.8. Реквот ноги — maintain_leg', level=2)
    add_para(doc,
             'Решение по СОБСТВЕННОМУ учёту (leg[\'order_id\'], leg[\'price_old\']), '
             'а не по order_dict — иначе можно снять свежевыставленную заявку, пока '
             'событие по ней ещё в пути. Логика:')
    add_bullet(doc, 'исполнение проверяется ДО отмены (leg_filled);')
    add_bullet(doc, 'если целевая цена вне спреда (для продажи выше ask, для '
                    'покупки ниже bid) — снятие и ожидание (заявка с ценой вне '
                    'спреда не выставляется);')
    add_bullet(doc, 'цена не изменилась и объём совпал — ничего не делаем (\'keep\');')
    add_bullet(doc, 'цена изменилась — отмена и перевыставление (_requote);')
    add_bullet(doc, '«приём потерянной заявки»: своей нет, а в order_dict есть '
                    'активная наша заявка (по symbol+side, client_order_id с '
                    'префиксом filename) — она принимается на учёт;')
    add_bullet(doc, 'иначе выставление новой заявки.')
    add_para(doc,
             '_requote ограничивает объём остатком до целевого qty: исполненная '
             'ранее часть не дублируется; при отказе PlaceOrder — красный '
             'светодиод и сообщение.')

    # ================= 3. РЕЖИМЫ =================
    add_heading(doc, '3. Особенности работы в каждом режиме', level=1)

    add_heading(doc, '3.0. Общее для всех режимов — правило effective_profit '
                     '(Diff.select)', level=2)
    add_para(doc,
             'Галки Th и Sp НЕЗАВИСИМЫ (в любом сочетании): Th добавляет в выборку '
             'Diff.theor, Sp — Diff.spread (при «заражении» середины — последнее '
             'валидное; недоступное значение в выборку не попадает). В Open '
             'берётся НАИМЕНЬШЕЕ из выборки (Профит, Th, Sp) — агрессивнейший '
             'профит; в Close — НАИБОЛЬШЕЕ; Waiting — сырой Профит. Активные '
             'значения берутся из набора действующего режима: applied_mode / '
             'expected_profit / theor_flag / spread_flag; предрасчёт передаёт их '
             'явно из набора выбранного режима (sel_* в _preview_targets_impl).')

    add_heading(doc, '3.1. Режим Open (открытие позиций)', level=2)
    add_bullet(doc, 'Профит open из Spinbox; применяется набор флагов Th/Sp строки Open.')
    add_bullet(doc, 'Число циклов по умолчанию 1 (при ручном переключении).')
    add_bullet(doc, 'Ноги в исходном положении; при переходе из Close — возврат '
                    '(swap_legs), legs_swapped=False.')
    add_bullet(doc, 'Diff.select = min выборки.')

    add_heading(doc, '3.2. Режим Close (закрытие позиций — переворот)', level=2)
    add_bullet(doc, 'Профит close из Spinbox; набор флагов строки Close.')
    add_bullet(doc, 'При переходе Open -> Close: swap_legs — опционы '
                    'продажи/покупки меняются местами (со всеми подписками, типами '
                    'Call/Put радиокнопок, комбобоксами), legs_swapped=True; тип '
                    'опциона берётся у самого инструмента '
                    '(option_type_by_dataname), а не у прежнего положения '
                    'радиокнопки.')
    add_bullet(doc, 'Число циклов по умолчанию default_lot_count_close(): минимум '
                    'абсолютных позиций двух ног (сколько полных пар можно закрыть).')
    add_bullet(doc, 'Diff.select = max выборки.')
    add_bullet(doc, 'При смене режима: счётчик «Пар исполнено» обнуляется (новая '
                    'торговая задача), cleanup активного движка, пересборка ног '
                    '(engine.legs = build_legs()).')
    add_bullet(doc, 'ПОРЯДОК ОПЕРАЦИЙ в set_mode критичен: applied_mode '
                    'публикуется ПОСЛЕДНИМ (после сброса счётчика и пересборки '
                    'ног) — это флаг готовности для wait_signal; иначе движок '
                    'успевает начать пару со старыми ногами/счётчиком и молча '
                    'завершается.')

    add_heading(doc, '3.3. Режим Auto', level=2)
    add_bullet(doc, 'Сигнал (auto_signal_mode) вычисляется из Diff.theor И '
                    'Diff.spread против Profit open/close из Spinbox: хотя бы одна '
                    'доступная величина <= Profit open -> Open; иначе хотя бы одна '
                    '>= Profit close -> Close; обе в промежуточной зоне -> None = '
                    'Waiting. Недоступная величина (None или «заражённая» без '
                    'истории) исключается — работает другая; если недоступны обе — '
                    'движок ждёт. Конфликт зон разрешается в пользу Open (порядок '
                    'условий в постановке задачи).')
    add_bullet(doc, 'Галки Th/Sp на СИГНАЛ не влияют (в сигнале участвуют обе '
                    'величины всегда); они управляют только выбором значения для '
                    'таргет-цен.')
    add_bullet(doc, 'Waiting: жёлтый светодиод, заявки не выставляются, движок жив '
                    '(не завершается). refresh_signal_values() на каждой итерации '
                    'обновляет Diff.theor и Diff.spread — иначе сигнал застыл бы '
                    'на момент ухода в Waiting и условие никогда не сработало бы '
                    '(compute_targets в Waiting не вызывается, а предрасчёт GUI '
                    'обновляет значения только при остановленном движке). Заявок в '
                    'Waiting нет — «заражение» невозможно, last_valid пополняется.')
    add_bullet(doc, 'Сработка сигнала: GUI (check_auto_signal, опрос раз в 2 с) '
                    'вызывает set_mode(effective_mode(app)): применяет Open/Close '
                    'со всеми операциями (перестановка ног для Close, сброс '
                    'счётчика, пересборка ног). В Auto число циклов, выбранное '
                    'оператором, СОХРАНЯЕТСЯ (не сбрасывается в 1 при возврате в '
                    'Open).')
    add_bullet(doc, 'Звук play_auto_signal — движок сам переключился в новый режим.')
    add_bullet(doc, 'Исчерпание циклов: idle_auto() — движок остаётся жив, ждёт '
                    'смены сигнала; при смене применённого режима счётчик обнулится '
                    'и циклы продолжатся.')
    add_bullet(doc, 'Поджатие таргет-цен: tighten_auto_profit после каждой успешной '
                    'пары (см. 2.6, п.6).')

    add_heading(doc, '3.4. Предустановка переворота (apply_reversal_preset)', level=2)
    add_para(doc,
             'По реальной Difference position (разница IV открытых позиций, только '
             'когда по обеим ногам есть позиции и IV открытия рассчитаны): в Open '
             'заранее задаётся Profit close = Diff.pos + Sel.profit, в Close — '
             'Profit open = Diff.pos - Sel.profit. Пересчитывается при каждом '
             'обновлении Difference position и заменяет Profit противоположного '
             'режима, который будет использован при перевороте ног. Значение '
             'пишется и в Spinbox.')

    add_heading(doc, '3.5. Общая индикация', level=2)
    add_para(doc,
             'Светодиод: серый — остановлен; жёлтый — работает без заявок '
             '(Waiting, вне спреда, снятие, ожидание); светло-зелёный — '
             'заявки/встречная заявка стоят; красный — отказ выставления заявки. '
             'Строка режима — действующий Open/Close/Waiting. Вне торговой сессии: '
             'заявки сняты, движок ждёт открытия; run() при старте вне сессии ждёт '
             'до 10 попыток (wait_session), после — finish().')

    # ================= 4. ФУНКЦИИ =================
    add_heading(doc, '4. Краткое описание назначения каждой функции', level=1)

    add_heading(doc, '4.1. Служебные', level=2)
    add_bullet(doc, 'next_client_order_id — уникальный client_order_id не длиннее '
                    '20 символов.')
    add_bullet(doc, 'utc_to_msk_datetime — перевод времени UTC в московское.')

    add_heading(doc, '4.2. Обработчики стримов Finam', level=2)
    add_bullet(doc, '_on_account_info — парсинг портфеля: кэш, ГО (FORTS/MC/MCT), '
                    'позиции (количество, средняя цена, нереализованный профит) в '
                    '_account_data[0].')
    add_bullet(doc, '_to_float — числовое поле proto-Decimal (строка) -> float, '
                    'пустое -> 0.0.')
    add_bullet(doc, '_side_name / _status_name — человекочитаемые '
                    'направление/статус заявки.')
    add_bullet(doc, '_on_order — обновление order_dict по symbol; лог СВОИХ заявок '
                    '(по префиксу client_order_id) только в активных статусах и '
                    'терминальных после активных (дедуп лога _own_orders_seen; '
                    'стартовый пул старых заявок в лог не попадает).')
    add_bullet(doc, '_on_trade — накопительная запись сделок по заявке: дедуп по '
                    'trade_id (переподключения стрима дублируют сделки), накопление '
                    'filled_qty, средневзвешенной цены; _register_trade — в кэш '
                    'активных сделок.')
    add_bullet(doc, 'fill_info — (объём, средняя цена) по заявке; объём — из '
                    'order_dict (executed_quantity, авторитетный источник: стрим '
                    'сделок может терять события), цена — из накопленных сделок, '
                    'иначе лимитная цена заявки.')
    add_bullet(doc, 'order_dict_order — заявка из order_dict по order_id.')

    add_heading(doc, '4.3. Подписки на котировки', level=2)
    add_bullet(doc, '_on_new_quotes — инкрементальное обновление new_quotes: пустые '
                    'поля (0/None) не затирают предыдущие значения (частичный тик '
                    'не обнуляет last_price); от Алора/Финама приходят ask, bid, '
                    'implied_volatility, theoretical_price, last_price.')
    add_bullet(doc, 'subscribe_instrument / unsubscribe_instrument / unsubscribe_all '
                    '— управление подписками по symbol (guid хранится в '
                    'subscriptions_dict).')

    add_heading(doc, '4.4. Данные опционов и расчёт IV', level=2)
    add_bullet(doc, 'get_option_data_alor — справка опциона из Алора в options_data.')
    add_bullet(doc, '_parse_expiration — парсинг endExpiration (доли секунды '
                    'обрезаются до 6 знаков под isoformat).')
    add_bullet(doc, 'get_option_data_for_calc_price — (S, K, T, opt_type) для '
                    'Блэка–Шоулза; S — цена базового фьючерса из потока Финам.')
    add_bullet(doc, 'option_price — цена опциона по Блэку–Шоулзу (r = 0).')
    add_bullet(doc, '_newton_vol — IV общим солвером (Ньютон от стартового '
                    'приближения); newton_vol_call / newton_vol_put — обёртки с '
                    'ветвлениями по типу.')
    add_bullet(doc, 'round_step — округление цены вниз к шагу цены.')
    add_bullet(doc, '_expiration_of — datetime экспирации или None.')
    add_bullet(doc, 'diff_iv — разница IV в п.п.: «дальняя» нога (больше страйк, '
                    'при равных — старше серия) минус «ближняя».')
    add_bullet(doc, 'leg_mid_iv — IV середины спреда ноги: среднее IV сторон ask/bid.')
    add_bullet(doc, 'update_diff_spread — Diff.spread с детекцией «заражения» (своя '
                    'живая заявка на best ask/bid) и заморозкой на последнее '
                    'валидное; store=False — не пополнять last_valid (для '
                    'initial_offset и предрасчёта, чья середина может быть '
                    'заражена).')
    add_bullet(doc, 'opt_type_of / sign_of — тип опциона и знак оффсета (CALL +1, '
                    'PUT -1).')
    add_bullet(doc, '_sigma_of — рабочая IV: из потока Финам '
                    '(implied_volatility), иначе из Алора (volatility).')
    add_bullet(doc, 'leg_market — (ask, bid, ask_iv, bid_iv, theor_iv) по ноге или '
                    'None, если котировок нет (нет любой из сторон ask/bid). IV '
                    'сторон считаются методом Ньютона; theor_iv — сначала биржевая '
                    'implied_volatility из потока, fallback — Ньютон от '
                    'теоретической цены Финама, затем от theorPrice Алора '
                    '(смешивание источников искажает Diff.theor).')
    add_bullet(doc, 'leg_iv — IV по цене сделки (Ньютон) или ValueError.')
    add_bullet(doc, 'positions_quantity — количество лотов позиции по тикеру (со '
                    'знаком).')

    add_heading(doc, '4.5. Учёт сделок', level=2)
    add_bullet(doc, 'class Entry / class FIFO — инвентарь позиций FIFO: входы '
                    'закрывают противоположные записи, остаётся агрегат; открытие '
                    'фиксируется по IV.')
    add_bullet(doc, '_normalize_trades_df / refresh_trades / get_trades_df / '
                    'get_trades_all_df — кэш активных сделок: CSV (ведётся внешней '
                    'программой) + свежие сделки из потока; полное чтение истории — '
                    'тем же источником.')
    add_bullet(doc, 'open_iv_safe — IV открытой позиции по опциону или 0, если '
                    'позиции нет.')
    add_bullet(doc, '_trade_datetime / _register_trade — время сделки формата CSV; '
                    'сделка из потока в кэш + перечитывание CSV.')

    add_heading(doc, '4.6. Заявки', level=2)
    add_bullet(doc, 'place_order — лимитная заявка через Финам (PlaceOrder), '
                    'возвращает order_id.')
    add_bullet(doc, 'get_cancel_order — отмена заявки; отклонение отмены (уже '
                    'неактивна) — не ошибка учёта, лог уровня info.')
    add_bullet(doc, 'order_alive — True, если заявку ещё имеет смысл отменять '
                    '(активна или данных о ней нет — безопаснее пробовать).')
    add_bullet(doc, 'active_order — активная заявка по symbol+side '
                    '(NEW/PARTIALLY_FILLED/...).')
    add_bullet(doc, 'cancel_active — отмена активной заявки.')

    add_heading(doc, '4.7. Движок и правила профита', level=2)
    add_bullet(doc, 'build_legs — словарь ног {\'sell\': {...}, \'buy\': {...}} '
                    '(доступ по ключам, НЕ распаковывать словарь).')
    add_bullet(doc, 'effective_profit — правило выбора профита (см. раздел 3).')
    add_bullet(doc, 'initial_offset — оффсеты в п.п. IV с применением правила; при '
                    'недоступности котировок — sign * profit (фолбэк на Профит).')
    add_bullet(doc, 'tighten_auto_profit — поджатие Profit open/close к фактическому '
                    'Profit последней успешной пары (только Auto).')

    add_heading(doc, '4.8. QuoterEngine — торговый движок (поток)', level=2)
    add_bullet(doc, 'say / set_led / set_status — сообщение/светодиод/статус через '
                    'msg_queue.')
    add_bullet(doc, 'session_active — активна ли торговая сессия (расписание MOEX).')
    add_bullet(doc, 'wait_session — ожидание начала сессии (до 10 попыток по 3 с).')
    add_bullet(doc, 'refresh_signal_values — обновление Diff.theor/Diff.spread вне '
                    'торговых фаз (обязательно для сигнала Auto в Waiting).')
    add_bullet(doc, 'wait_signal — ожидание выхода из промежуточной зоны Auto; после '
                    'сработки ждёт применения режима GUI (applied_mode), если сигнал '
                    'вернулся в Waiting — возвращается, а не начинает пару вслепую.')
    add_bullet(doc, 'idle_auto — ожидание новой торговой задачи после исчерпания '
                    'циклов.')
    add_bullet(doc, 'cleanup — снятие всех активных заявок движка, сброс состояния '
                    'ног.')
    add_bullet(doc, 'leg_filled — суммарное исполнение по всем заявкам ноги: (лоты, '
                    'средняя).')
    add_bullet(doc, 'log_new_trades — сообщения о новых сделках.')
    add_bullet(doc, 'compute_targets — расчётное ядро (см. 2.7).')
    add_bullet(doc, 'maintain_leg — реквот ноги (см. 2.8).')
    add_bullet(doc, '_requote — перевыставление заявки с ограничением объёма '
                    'остатком.')
    add_bullet(doc, 'cancel_leg — снятие заявки ноги со сбросом состояния.')
    add_bullet(doc, 'run — внешний цикл движка (см. 2.6).')
    add_bullet(doc, 'finish — cleanup + серый светодиод + Stopped.')
    add_bullet(doc, 'run_pair — фаза 1 (обе заявки, быстрый опрос, передача в '
                    'run_balance).')
    add_bullet(doc, 'run_balance — фаза 2 (встречная заявка по sec.target, переквот, '
                    'учёт pending, приём потерянной заявки).')
    add_bullet(doc, 'emit_panel — публикация состояния в панель GUI.')

    add_heading(doc, '4.9. GUI-логика (функции уровня модуля)', level=2)
    add_bullet(doc, 'on_base_asset_change / on_expiration_date_change — выбор '
                    'базового актива и экспирации, загрузка доски опционов и '
                    'справки Алора.')
    add_bullet(doc, 'get_option_type_sell / get_option_type_buy — типы опционов ног '
                    'из GUI.')
    add_bullet(doc, 'update_option_pos_labels — подписи с тикерами и позициями ног.')
    add_bullet(doc, 'on_instrument_changed — сброс счётчика пар при смене '
                    'инструмента.')
    add_bullet(doc, 'selected_sell / selected_buy — текущие выбранные опционы ног.')
    add_bullet(doc, 'toggle_flags (первое определение, стр. 1778) — НЕИСПОЛЬЗУЕМЫЙ '
                    'дубликат (перекрыт вторым определением; см. раздел 5).')
    add_bullet(doc, 'toggle_flags (второе определение, стр. 2059, его привязаны '
                    'галки GUI) — независимые галки Th/Sp: применение к набору '
                    'Open/Close, синхронизация активных флагов, если набор '
                    'принадлежит действующему режиму.')
    add_bullet(doc, 'preview_targets / _preview_targets_impl — предрасчёт без '
                    'выставления заявок: sel-набор режима (радиокнопка; в Auto — '
                    'применённый сигнал, до первой сработки — текущий сигнал, иначе '
                    'Waiting), оффсеты, таргеты (с учётом indent, как в '
                    'maintain_leg), Diff-показатели; печать диагностики (Режим, '
                    'Профит, флаги, IV сторон, Diff.market, Difference pos) при '
                    'verbose.')
    add_bullet(doc, 'active_mode / effective_mode — выбранный радиокнопкой режим / '
                    'действующий режим (в Auto — по сигналу, None = Waiting).')
    add_bullet(doc, 'difference_position_real — Difference position по реальным '
                    'позициям и IV открытия; (None, False), если данных '
                    'недостаточно.')
    add_bullet(doc, 'apply_reversal_preset — предустановка переворота (см. 3.4).')
    add_bullet(doc, 'auto_spread_value — Diff.spread для сигнала: текущее или '
                    'последнее валидное.')
    add_bullet(doc, 'auto_signal_mode — сигнал Auto по двум величинам (см. 3.3).')
    add_bullet(doc, 'auto_waiting — True, если Auto и обе величины в промежуточной '
                    'зоне.')
    add_bullet(doc, 'selected_profit — применение значения поля Профит (Open/Close): '
                    'запись в глобальные параметры, нормализация текста (запятая '
                    'как разделитель, диапазон -20..20), вызов предрасчёта; при '
                    'посимвольном вводе (rewrite=False) поле не перезаписывается, '
                    'иначе точка затиралась бы.')
    add_bullet(doc, 'toggle_theor — синхронизация активных флагов с галками перед '
                    'стартом движка (лечит NameError из удалённой старой логики).')
    add_bullet(doc, 'option_type_by_dataname — тип опциона ноги по данным или '
                    'спискам доски.')
    add_bullet(doc, 'swap_legs — перестановка ног (см. 3.2).')
    add_bullet(doc, 'default_lot_count_close — число циклов Close: минимум '
                    'абсолютных позиций.')
    add_bullet(doc, 'set_trading_mode_label — метка действующего режима в строке '
                    'счётчика.')
    add_bullet(doc, 'set_mode — применение режима (см. 3.2, порядок операций '
                    'критичен).')
    add_bullet(doc, 'on_mode_change — переключение радиокнопки.')
    add_bullet(doc, 'check_auto_signal — опрос Auto из GUI раз в 2 с; в ручных '
                    'режимах применяет выбранный режим (no-op, если уже применён).')
    add_bullet(doc, 'selected_select_profit — применение Sel.profit.')
    add_bullet(doc, 'selected_lot_count / selected_basket_size / selected_timeout / '
                    'selected_indent — применение числовых параметров GUI.')
    add_bullet(doc, 'play_sound_file / play_auto_signal / play_pair_signal — звуковые '
                    'сигналы (.wav из папки скрипта, неблокирующе): смена режима '
                    'Auto, успешная пара.')

    add_heading(doc, '4.10. class App (GUI)', level=2)
    add_bullet(doc, '__init__ — построение окна: панель управления (базовый актив, '
                    'экспирация, типы и опционы ног, режим, профиты, Sel.profit, '
                    'число циклов, объём, timeout, indent, галки Th/Sp двух '
                    'наборов, кнопка Старт/Стоп, светодиод, счётчик «Пар '
                    'исполнено», метка режима), панель предрасчёта (SEL/BUY '
                    'таргеты, Diff-показатели), текстовое окно лога; запуск трёх '
                    'таймеров.')
    add_bullet(doc, '_schedule_preview — периодический предрасчёт + опрос Auto.')
    add_bullet(doc, 'add_message — сообщение в лог (потокобезопасно через after).')
    add_bullet(doc, '_refresh_csv — периодическое перечитывание CSV.')
    add_bullet(doc, '_poll_messages — выкачивание msg_queue.')
    add_bullet(doc, 'start_quoter / stop_quoter / exit — старт (toggle_theor по '
                    'обоим наборам, set_mode, QuoterEngine, поток), стоп '
                    '(running=False), выход (unsubscribe_all, уничтожение окна).')

    add_heading(doc, '4.11. Корневой уровень', level=2)
    add_bullet(doc, '(выполняется при импорте) — подписки, потоки Финам, '
                    'refresh_trades, sleep(5).')
    add_bullet(doc, 'if __name__ == \'__main__\' — создание App и mainloop.')

    # ================= 5. ОПТИМИЗАЦИЯ =================
    add_heading(doc, '5. Рекомендации по возможной оптимизации кода', level=1)

    add_para(doc, '5.1. УДАЛИТЬ дубликат toggle_flags (стр. 1778).', bold=True)
    add_para(doc,
             'Второе определение (стр. 2059) перекрывает первое, все привязки GUI '
             'указывают на второе. Первый — мёртвый код и источник риска «правок '
             'не в тот файл» (правка мёртвой копии не даёт эффекта). Отличия двух '
             'копий: первая синхронизирует активные флаги по '
             'radio_mode/applied_mode, вторая — по effective_mode; поведение при '
             'Auto-Waiting у них разное — выбрать желаемое и оставить одно '
             'определение.')

    add_para(doc, '5.2. Деградация при неполном стакане.', bold=True)
    add_para(doc,
             'leg_market возвращает None, если отсутствует ЛЮБАЯ из сторон ask/bid '
             '— при пустой стороне стакана вся итерация пропускается. Возможное '
             'развитие: котирование от доступной стороны (согласованное правило '
             'для обеих ног), либо «залипание» последнего валидного стакана с '
             'явной пометкой в панели.')

    add_para(doc, '5.3. Кэширование IV Ньютона.', bold=True)
    add_para(doc,
             'leg_market пересчитывает IV обеих сторон на каждой итерации (движок '
             'раз в timeout + фазы 0.1 с в фазах, плюс предрасчёт GUI). Дешевле '
             'пересчитывать IV только при изменении цены (дедуп по цене) — '
             'Ньютоны по тем же ценам идентичны.')

    add_para(doc, '5.4. Потокобезопасность глобальных значений.', bold=True)
    add_para(doc,
             'new_quotes, order_dict, trade_dict, options_data, Diff-переменные и '
             'параметры читаются и пишутся из обработчиков стримов и торгового '
             'потока без блокировок. Для словарей это практически безопасно (GIL, '
             'атомарные операции), но составные проверки-затем-действия (например, '
             'leg_filled -> cancel) атомарности не имеют. При переносе на другой '
             'интерпретатор или асинхронный цикл — ввести Lock или копировать '
             'снапшоты.')

    add_para(doc, '5.5. Нереальная отписка.', bold=True)
    add_para(doc,
             'unsubscribe_instrument вызывает отписку, но подписки Финам держатся '
             'по guid; фактический набор стоит сверять (иначе незакрытые подписки '
             'копятся при перестановках ног).')

    add_para(doc, '5.6. Дедупликация логов и объём лога.', bold=True)
    add_para(doc,
             '_on_order логирует каждую заявку целиком на уровне info (в потоке '
             'заявок много чужих событий) — целесообразно вынести в debug или '
             'фильтровать по «своим» до лога.')

    add_para(doc, '5.7. Опрос исполнений в фазах фиксированным шагом 0.1 с.', bold=True)
    add_para(doc,
             'Заменить на событийный (ожидание по условной переменной/очереди), '
             'пробуждаемый _on_trade/_on_order: меньше CPU и меньше задержка '
             'реакции.')

    add_para(doc, '5.8. SQL/CSV-кэш.', bold=True)
    add_para(doc,
             'refresh_trades перечитывает весь CSV каждые 15 с и при каждой сделке; '
             'при росте истории файл станет узким местом — хранить индекс последней '
             'прочитанной строки или перейти на sqlite/parquet.')

    add_para(doc, '5.9. Модульные тесты чистых функций.', bold=True)
    add_para(doc,
             'diff_iv, effective_profit, initial_offset, auto_signal_mode, '
             'round_step, _parse_expiration легко тестируются без сети и GUI. Это '
             'профилактика уже случавшихся регрессий («потерянные правки», '
             'рассинхронизация версий файла).')

    add_para(doc, '5.10. Разделение файла.', bold=True)
    add_para(doc,
             'Расчётное ядро (БШ/Ньютон), торговая логика и GUI вынести в модули — '
             'упростит тестирование и устранит конфликты глобальных имён (основной '
             'источник правок «не туда»).')

    # ================= 6. РАЗВИТИЕ =================
    add_heading(doc, '6. Направления дальнейшего развития возможностей программы', level=1)

    add_para(doc, '6.1. Резервный источник данных (fallback).', bold=True)
    add_para(doc,
             'Доска опционов MOEX ISS (optionboard.json) отдаёт страйк, тип, '
             'теорцену, волатильность, bid/offer, открытый интерес по ВСЕЙ серии '
             'одним запросом — полное замещение справки Алора при её отказе; тикеры '
             'ROPD несут суффикс \'B\', при маппинге отрезать. UNDERLYINGSETTLEPRICE '
             'блока asset — согласованная с кривой волатильности оценка базового '
             'фьючерса: можно использовать как S в расчётах (или для сверки с '
             'потоком Финам).')

    add_para(doc, '6.2. Контроль допустимых цен.', bold=True)
    add_para(doc,
             'Лимиты цены опциона биржа в API не публикует — они динамические '
             '(коридор вокруг теоретической цены при сдвинутых сценариях БА и '
             'волатильности). Грубая защита: сверка цены заявки с теоретической '
             '(SETTLEPRICE/theorPrice) — отклонять при отличии в разы. Точный '
             'коридор: параметры сдвига клирингового центра задать константами и '
             'считать обе границы через option_price.')

    add_para(doc, '6.3. Работа с неполным стаканом (см. 5.2) + валидация ширины '
                  'спреда IV стороны.', bold=True)
    add_para(doc,
             'При разрыве IV ask/bid одной ноги больше порога середина недостоверна '
             '(чужой «мусорный» выброс или замороженный стакан вне сессии) — '
             'замораживать Diff.spread на последнем валидном и логировать эпизод.')

    add_para(doc, '6.4. Денежный профит.', bold=True)
    add_para(doc,
             'Расчёт фактической прибыли пары в рублях с учётом комиссий, ГО и '
             'пункта стоимости (STEVETIME/шаг цены), запись в CSV истории сделок — '
             'база для статистики и отчётов.')

    add_para(doc, '6.5. Звуковые и внешние алерты.', bold=True)
    add_para(doc,
             'Помимо текущих .wav — Telegram/webhook уведомления о исполненных '
             'парах, ошибках, вне-сессионных событиях.')

    add_para(doc, '6.6. Дельта-нейтральный режим.', bold=True)
    add_para(doc,
             'Выбор объёма второй ноги по дельтам (хеджирование) вместо 1:1; '
             'потребуется греки из Алора или расчёт формулой.')

    add_para(doc, '6.7. Оптимизатор выбора пар.', bold=True)
    add_para(doc,
             'Автоподбор пар по ликвидности (VOLTODAY, OPENPOSITION, ширина спреда) '
             'и текущей Diff — сейчас выбор пары полностью ручной.')

    add_para(doc, '6.8. Персистентность состояния.', bold=True)
    add_para(doc,
             'Сохранение счётчика пар, Profit, флагов и статистики в JSON — '
             'переживание перезапуска без ручной настройки.')

    add_para(doc, '6.9. Визуализация.', bold=True)
    add_para(doc,
             'График Diff.theor/Diff.spread/Diff.select во времени (например, '
             'tkinter.Canvas или web-панель) — наглядная настройка порогов Profit '
             'open/close.')

    # ================= ФУТЕР =================
    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = footer.add_run('— Конец документа —')
    r.font.name = 'Times New Roman'
    r.font.size = Pt(10)
    r.italic = True
    r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    return doc


if __name__ == '__main__':
    document = build_document()
    out = '09MyQuoter_Описание.docx'
    document.save(out)
    print(f'Готово: {out}')