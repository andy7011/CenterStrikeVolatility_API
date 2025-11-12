OnTrade()
Функция вызывается терминалом QUIK при получении сделки (Таблица сделок).

Функция возвращает таблицу, поля которой перечислены в примере:

function OnTrade(trade)

   message("Идентификатор транзакции "..tostring(trade.trans_id));-- NUMBER
   message("Номер сделки в торговой системе "..tostring(trade.trade_num));-- NUMBER
   message("Номер заявки в торговой системе "..tostring(trade.order_num));-- NUMBER
   message("Комментарий "..tostring(trade.brokerref));-- STRING  обычно: <код клиента>/<номер поручения>
   message("Идентификатор трейдера "..tostring(trade.userid));-- STRING
   message("Идентификатор дилера "..tostring(trade.firmid));-- STRING
   message("Торговый счет "..tostring(trade.account));-- STRING
   message("Цена "..tostring(trade.price));-- NUMBER
   message("Количество бумаг в последней сделке в лотах "..tostring(trade.qty));-- NUMBER
   message("Объем в денежных средствах "..tostring(trade.value));-- NUMBER
   message("Накопленный купонный доход "..tostring(trade.accruedint));-- NUMBER
   message("Доходность "..tostring(trade.yield));-- NUMBER
   message("Код расчетов "..tostring(trade.settlecode));-- STRING
   message("Код фирмы партнера "..tostring(trade.cpfirmid));-- STRING
   message("Набор битовых флагов "..tostring(trade.flags));-- NUMBER
      -- бит 0 (0x1)  Заявка активна, иначе – не активна
      -- бит 1 (0x2)  Заявка снята. Если флаг не установлен и значение бита «0» равно «0», то заявка исполнена
      -- бит 2 (0x4)  Заявка на продажу, иначе – на покупку. Данный флаг для сделок и сделок для исполнения определяет направление сделки (BUY/SELL)
      -- бит 3 (0x8)  Заявка лимитированная, иначе – рыночная
      -- бит 4 (0x10)  Разрешить / запретить сделки по разным ценам
      -- бит 5 (0x20)  Исполнить заявку немедленно или снять (FILL OR KILL)
      -- бит 6 (0x40)  Заявка маркет-мейкера. Для адресных заявок – заявка отправлена контрагенту
      -- бит 7 (0x80)  Для адресных заявок – заявка получена от контрагента
      -- бит 8 (0x100)  Снять остаток
      -- бит 9 (0x200)  Айсберг-заявка

   message("Цена выкупа "..tostring(trade.price2));-- NUMBER
   message("Ставка РЕПО (%) "..tostring(trade.reporate));-- NUMBER
   message("Код клиента "..tostring(trade.client_code));-- STRING
   message("Доход (%) на дату выкупа "..tostring(trade.accrued2));-- NUMBER
   message("Сумма РЕПО "..tostring(trade.repovalue));-- NUMBER
   message("Объем выкупа РЕПО "..tostring(trade.repo2value));-- NUMBER
   message("Начальный дисконт (%) "..tostring(trade.start_discount));-- NUMBER
   message("Нижний дисконт (%) "..tostring(trade.lower_discount));-- NUMBER
   message("Верхний дисконт (%) "..tostring(trade.upper_discount));-- NUMBER
   message("Блокировка обеспечения "..tostring(trade.block_securities));-- NUMBER («Да»/«Нет»)
   message("Клиринговая комиссия (ММВБ) "..tostring(trade.clearing_comission));-- NUMBER
   message("Комиссия Фондовой биржи (ММВБ) "..tostring(trade.exchange_comission));-- NUMBER
   message("Комиссия Технического центра (ММВБ) "..tostring(trade.tech_center_comission));-- NUMBER
   message("Дата расчетов "..tostring(trade.settle_date));-- NUMBER
   message("Валюта расчетов "..tostring(trade.settle_currency));-- STRING
   message("Валюта "..tostring(trade.trade_currency));-- STRING
   message("Код биржи в торговой системе "..tostring(trade.exchange_code));-- STRING
   message("Идентификатор рабочей станции "..tostring(trade.station_id));-- STRING
   message("Код бумаги заявки "..tostring(trade.sec_code));-- STRING
   message("Код класса "..tostring(trade.class_code));-- STRING
   message("Дата и время "..tostring(trade.datetime));-- TABLE
   message("Идентификатор расчетного счета/кода в клиринговой организации "..tostring(trade.bank_acc_id));-- STRING
   message("Комиссия брокера "..tostring(trade.broker_comission));-- NUMBER  Отображается с точностью до 2 двух знаков. Поле зарезервировано для будущего использования.
   message("Номер витринной сделки в Торговой Системе "..tostring(trade.linked_trade));-- NUMBER для сделок РЕПО с ЦК и SWAP
   message("Период торговой сессии "..tostring(trade.period));-- NUMBER  Возможные значения:
      -- "0" – Открытие;
      -- "1" – Нормальный;
      -- "2" – Закрытие

end;

Пример использования:

function OnTrade(trade)
   -- Если сработал "Стоп-лосс и Тейк-профит"
   if trade.order_num == SlTpOrderNum then
      SlTpTradeNum = trade.trade_num;
      SlTpTradePrice = trade.price;
   end;
end;