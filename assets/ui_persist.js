/**
 * Сохранение зума и выбора в легенде при обновлении графиков Dash.
 *
 * Dash при plotly_relayout записывает диапазоны осей в figure-prop и вызывает
 * лишний Plotly.react, из-за чего plotly удаляет сохранённое GUI-состояние
 * (_preGUI), а следующий колбэк присылает свежую figure -> зум и видимость
 * трейсов сбрасываются. Патч перед каждым Plotly.react возвращает текущее
 * состояние графика в поступающую figure.
 */
(function () {
    function applyState(gd, fig) {
        try {
            if (!gd || !gd._fullLayout || !gd._fullData || !fig) return fig;
            var layout = fig.layout = fig.layout || {};

            // Диапазоны осей (zoom/pan) с флагом autorange
            ['xaxis', 'yaxis', 'yaxis2', 'yaxis3'].forEach(function (ax) {
                var full = gd._fullLayout[ax];
                if (!full || !full._id) return;
                var target = layout[ax] = layout[ax] || {};
                if (full.autorange) {
                    target.autorange = true;
                    delete target.range;
                } else if (full.range) {
                    target.range = full.range.slice();
                    target.autorange = false;
                }
            });

            // Видимость трейсов (выбор в легенде) по имени трейса
            if (fig.data && fig.data.length) {
                var visByName = {};
                gd._fullData.forEach(function (tr) {
                    if (tr.name !== undefined) visByName[tr.name] = tr.visible;
                });
                fig.data.forEach(function (tr) {
                    if (tr.name in visByName) {
                        tr.visible = visByName[tr.name];
                    }
                });
            }
        } catch (e) { /* не мешать отрисовке */ }
        return fig;
    }

    function patch() {
        if (!window.Plotly || window.Plotly.__uiPersistPatched) return false;
        var origReact = Plotly.react;
        Plotly.react = function (gd, fig, config) {
            if (fig && fig.data) applyState(gd, fig);
            return origReact.apply(this, arguments);
        };
        Plotly.__uiPersistPatched = true;
        return true;
    }

    // plotly.js загружается лениво, поэтому ждём его появления
    var timer = setInterval(function () {
        if (patch()) clearInterval(timer);
    }, 50);
})();
