OnOrder()
Функция вызывается терминалом QUIK при получении новой заявки или при изменении параметров существующей заявки (Таблица заявок).

Функция возвращает таблицу, поля которой перечислены в примере:
function OnOrder(order)

   message("Номер заявки в торговой системе "..tostring(order.order_num));-- NUMBER
   message("Набор битовых флагов "..tostring(order.flags));-- NUMBER
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

   message("Комментарий "..tostring(order.brokerref));-- STRING  обычно: <код клиента>/<номер поручения>
   message("Идентификатор трейдера "..tostring(order.userid));-- STRING
   message("Идентификатор фирмы "..tostring(order.firmid));-- STRING
   message("Торговый счет "..tostring(order.account));-- STRING
   message("Цена "..tostring(order.price));-- NUMBER
   message("Количество в лотах "..tostring(order.qty));-- NUMBER
   message("Остаток "..tostring(order.balance));-- NUMBER
   message("Объем в денежных средствах "..tostring(order.value));-- NUMBER
   message("Накопленный купонный доход "..tostring(order.accruedint));-- NUMBER
   message("Доходность "..tostring(order.yield));-- NUMBER
   message("Идентификатор транзакции "..tostring(order.trans_id));-- NUMBER
   message("Код клиента "..tostring(order.client_code));-- STRING
   message("Цена выкупа "..tostring(order.price2));-- NUMBER
   message("Код расчетов "..tostring(order.settlecode));-- STRING
   message("Идентификатор пользователя "..tostring(order.uid));-- NUMBER
   message("Код биржи в торговой системе "..tostring(order.exchange_code));-- STRING
   message("Время активации "..tostring(order.activation_time));-- NUMBER
   message("Номер заявки в торговой системе "..tostring(order.linkedorder));-- NUMBER
   message("Дата окончания срока действия заявки "..tostring(order.expiry));-- NUMBER
   message("Код бумаги заявки "..tostring(order.sec_code));-- STRING
   message("Код класса заявки "..tostring(order.class_code));-- STRING
   message("Дата и время "..tostring(order.datetime));-- TABLE
   message("Дата и время снятия заявки "..tostring(order.withdraw_datetime));-- TABLE
   message("Идентификатор расчетного счета/кода в клиринговой организации "..tostring(order.bank_acc_id));-- STRING
   message("Способ указания объема заявки "..tostring(order.value_entry_type));-- NUMBER  Возможные значения:
      -- "0" – по количеству,
      -- "1" – по объему

   message("Срок РЕПО, в календарных днях "..tostring(order.repoterm));-- NUMBER
   message("Сумма РЕПО на текущую дату "..tostring(order.repovalue));-- NUMBER  Отображается с точностью 2 знака
   message("Объём сделки выкупа РЕПО "..tostring(order.repo2value));-- NUMBER  Отображается с точностью 2 знака
   message("Остаток суммы РЕПО "..tostring(order.repo_value_balance));-- NUMBER  за вычетом суммы привлеченных или предоставленных по сделке РЕПО денежных средств в неисполненной части заявки, по состоянию на текущую дату. Отображается с точностью 2 знака
   message("Начальный дисконт, в % "..tostring(order.start_discount));-- NUMBER
   message("Причина отклонения заявки брокером "..tostring(order.reject_reason));-- STRING
   message("Битовое поле для получения специфических параметров с западных площадок "..tostring(order.ext_order_flags));-- NUMBER
   message("Минимально допустимое количество "..tostring(order.min_qty));-- NUMBER  которое можно указать в заявке по данному инструменту. Если имеет значение «0», значит ограничение по количеству не задано
   message("Тип исполнения заявки "..tostring(order.exec_type));-- NUMBER  Если имеет значение «0», значит значение не задано
   message("Поле для получения параметров по западным площадкам "..tostring(order.side_qualifier));-- NUMBER  Если имеет значение «0», значит значение не задано
   message("Поле для получения параметров по западным площадкам "..tostring(order.acnt_type));-- NUMBER  Если имеет значение «0», значит значение не задано
   message("Поле для получения параметров по западным площадкам "..tostring(order.capacity));-- NUMBER  Если имеет значение «0», значит значение не задано
   message("Поле для получения параметров по западным площадкам "..tostring(order.passive_only_order));-- NUMBER  Если имеет значение «0», значит значение не задано

end;

Пример использования:

-- Предварительно, при выставлении заявки Buy ее ID транзакции запоминается в переменной BuyUniqTransID
-- Соответственно Sell в SellUniqTransID

function OnOrder(order)
   -- Если выставлен Buy, запоминает номер заявки в торговой системе
   if order.trans_id == BuyUniqTransID and BuyOrderNum == 0 then
      BuyOrderNum = order.order_num;
   end;
   -- Если выставлен Sell, запоминает номер заявки в торговой системе
   if order.trans_id == SellUniqTransID and SellOrderNum == 0 then
      SellOrderNum = order.order_num;
   end;
end;