//Создание карты
var extent = [15522946.393668033, 5002641.018067474, 15751596.627757415, 5160979.444049783];
var projection = new ol.proj.Projection({
    code: 'xkcd-image',
    units: 'pixels',
    extent: extent,
});
var vectorLayer = new ol.layer.Vector({
    source: new ol.source.Vector(),
});

var map = new ol.Map({
    pixelRatio: 2,
    target: 'map', // ID элемента на странице, где отобразить карту
    layers: [
        new ol.layer.Image({
            name: 'Ships',
            visible: true,
            source: new ol.source.ImageStatic({
                url: '/static/images/clean/with_points_1.png', // карта с кораблями
                imageSize: [5983, 4143], // Размер изображения
                projection: projection,
                imageExtent: extent
            })
        }),
    ],
    view: new ol.View({
        projection: projection,
        center: ol.extent.getCenter(extent), // Координаты центра карты
        zoom: 2, // Масштаб карты
        minZoom: 2,
        maxZoom: 4,
        extent: extent
    }),
    controls: ol.control.defaults.defaults().extend([
        new ol.control.FullScreen(),
        // Добавление элемента управления для легенды
        new ol.control.Control({
            element: document.getElementById('legend')
        }),
        new ol.control.ZoomToExtent(extent)
    ])
});

map.addControl(new ol.control.LayerSwitcher({
    reverse: false
}));

//Создание легенды
var legendShown = false;

function hideLegend() {
    document.getElementById('legend').className = 'hide';
    legendShown = false;
}

function showLegend() {
    document.getElementById('legend').className = 'show';
    legendShown = true;
}

var button = new ol.control.Button({
    className: 'ol-legend ol-unselectable ol-control ol-collapsed', // класс для стилизации кнопки
    title: 'Данные работы алгоритма', // всплывающая подсказка для кнопки
    handleClick: function () { //
        if (legendShown) {
            document.getElementById('legend').className = 'hide';
            legendShown = false;
        } else {
            document.getElementById('legend').className = 'show';
            legendShown = true;
        }
    },
});
map.addControl(button); // добавление кнопки на карту
var legend = document.getElementById('legend');
map.getViewport().appendChild(legend);

//Забавы с курсором
map.getViewport().style.cursor = "auto";
//Ладошка
// map.getViewport().style.cursor = "-webkit-grab";
map.on('pointerdrag', function (evt) {
    map.getViewport().style.cursor = "-webkit-grabbing";
});
map.on('pointerup', function (evt) {
    map.getViewport().style.cursor = "auto";
});

const startCoordsEl = document.querySelector('#start_coords');
const EndCoordsEl = document.querySelector('#end_coords');
startCoordsEl.addEventListener('click', function () {
    map.getViewport().style.cursor = 'pointer';
});
EndCoordsEl.addEventListener('click', function () {
    map.getViewport().style.cursor = 'pointer';
});

//Заполнение полей координат
function setPoints() {
    let startPointInput = document.getElementById("start_coords");
    let endPointInput = document.getElementById("end_coords");
    const routeBtn = document.getElementById('do_graph');
    routeBtn.addEventListener('click', () => {
        startPointInput.style.display = 'inline';
        endPointInput.style.display = 'inline';
    });
    var checkFocus = (el) => el === document.querySelector(':focus');
    var onfocus = 0;
    window.addEventListener('click', e => {
        if (checkFocus(start_coords)) {
            onfocus = 1;
        } else if (checkFocus(end_coords)) {
            onfocus = 2;
        }


        map.on('click', function (evt) {
            let layers = map.getLayers().getArray();
            let coords = ol.proj.toLonLat(evt.coordinate).map(coord => coord.toFixed(6));

            if (onfocus === 1) {
                startPointInput.value = coords.toString();

                var StartPointLayer = null;

                for (let i = 0; i < layers.length; i++) {
                    if (layers[i].get('name') === 'StartPoint') {
                        StartPointLayer = layers[i];
                        break;
                    }
                }

                if (StartPointLayer) {
                    map.removeLayer(StartPointLayer);
                }

                const StartPoint = new ol.layer.Vector({
                    name: 'StartPoint',
                    source: new ol.source.Vector({
                        features: [
                            new ol.Feature({
                                geometry: new ol.geom.Point(evt.coordinate),
                            })
                        ]
                    }),
                    style: new ol.style.Style({
                        image: new ol.style.Icon({
                            anchor: [0.5, 1],
                            crossOrigin: 'anonymous',
                            scale: 0.07, // Установка масштаба иконки
                            src: '/static/images/markers/start_point.png',
                        })
                    })
                });

                map.addLayer(StartPoint);
                onfocus = null;
                map.getViewport().style.cursor = "auto";


            } else if (onfocus === 2) {
                endPointInput.value = coords.toString();

                var endPointLayer = null;
                for (let i = 0; i < layers.length; i++) {
                    if (layers[i].get('name') === 'EndPoint') {
                        endPointLayer = layers[i];
                        break;
                    }
                }

                if (endPointLayer) {
                    map.removeLayer(endPointLayer);
                }

                const EndPoint = new ol.layer.Vector({
                    name: 'EndPoint',
                    source: new ol.source.Vector({
                        features: [
                            new ol.Feature({
                                geometry: new ol.geom.Point(evt.coordinate),
                            })
                        ]
                    }),
                    style: new ol.style.Style({
                        image: new ol.style.Icon({
                            anchor: [0.5, 1],
                            crossOrigin: 'anonymous',
                            scale: 0.07, // Установка масштаба иконки

                            src: '/static/images/markers/end_point.png',
                        })
                    })
                });

                map.addLayer(EndPoint);
                onfocus = null;
                map.getViewport().style.cursor = "auto";


            }

        });
    });
}

setPoints();

//Обработка кнопки "Построить граф и проложить маршрут"
function Create_graph() {

    let polyLayerExists = false;
    let allLayers = map.getLayers().getArray();

    // Проверка на начальную кластеризацию данных
    for (let i = 0; i < allLayers.length; i++) {
        if (allLayers[i].get('name') === 'Polygons') {
            polyLayerExists = true;
            break;
        }
    }
    if (!polyLayerExists) {
        document.getElementById('do_cluster').style.cssText = 'box-shadow: 0px 0px 3px 3px #91B44AB2;';
        alert("Сначала необходимо кластеризовать данные");
    } else {
        // Получаем значения полей ввода
        const fields = ['distance_delta', 'weight_func_degree', 'angle_of_vision', 'weight_time_graph', 'weight_course_graph', 'search_algorithm', 'start_coords', 'end_coords'];
        const parameters_for_graph = {};
        let allFieldsFilled = true;
        var alert_list = []
        parameters_for_graph['points_inside'] = $('#points_inside').is(':checked');
        fields.forEach(field => {
            const value = document.getElementById(field).value;
            if (!value) {
                allFieldsFilled = false
                alert_list.push(field)
            }
            parameters_for_graph[field] = value;
        });

        // Если не все поля заполнены, выходим из функции
        if (!allFieldsFilled) return alert("Остались незаполненные поля: " + alert_list);
        if (!allFieldsFilled) return;

        if (parameters_for_graph['start_coords'] === parameters_for_graph['end_coords']) {
            return alert("Упс! Начальная точка совпадает с конечной. ")
        }

        $("#loader").show();

        $.ajax({
            type: 'POST',
            url: '/post_graphs_parameters',
            contentType: 'application/json',
            data: JSON.stringify(parameters_for_graph),
            success: function (data) {

                let allLayers = map.getLayers().getArray();
                for (let i = 0; i < allLayers.length; i++) {
                    if (allLayers[i].get('name') === 'Graph') {
                        map.removeLayer(allLayers[i]);
                        break
                    }
                }

                const GraphLayer = new ol.layer.Image({
                    name: 'Graph',
                    visible: true,
                    source: new ol.source.ImageStatic({
                        url: data[0], // URL PNG-изображения
                        imageSize: [5983, 4143], // Размер изображения
                        projection: projection,
                        imageExtent: extent,
                    })
                })

                for (let i = 0; i < allLayers.length; i++) {
                    if (allLayers[i].get('name') === 'StartPoint') {
                        var StartPoint = allLayers[i]
                        map.removeLayer(allLayers[i]);
                        break;
                    }
                }
                for (let i = 0; i < allLayers.length; i++) {
                    if (allLayers[i].get('name') === 'EndPoint') {
                        var EndPoint = allLayers[i]
                        map.removeLayer(allLayers[i]);
                        break;
                    }
                }


                map.addLayer(GraphLayer);
                map.addLayer(StartPoint);
                map.addLayer(EndPoint);


                const names = ["Clusters", "Polygons", "Ships"];
                names.forEach(name => {
                    const layers = map.getLayers().getArray();
                    layers.forEach(layer => {
                        if (layer.get('name') === name) {
                            layer.setVisible(false);
                        }
                    });
                });


                //Заполнение легенды данными из вычислительной части
                graph_data = data[1]
                let legend = document.getElementById('legend');

                //Перезаполнение при выборе других маршрутов
                let divsToRemove = legend.querySelectorAll('div:not(:first-child)');
                for (let i = 0; i < divsToRemove.length; i++) {
                    legend.removeChild(divsToRemove[i]);
                }

                let item = document.createElement('div');
                if ('Error' in graph_data) {
                    item.innerHTML = '<br><strong>' + graph_data['Error'] + '</strong>' + '<br>';
                } else {
                    item.innerHTML =
                        '<br>' + '<strong>Среднее отклонение от курсов на маршруте</strong>: ' + graph_data['Среднее отклонение от курсов на маршруте'] +
                        '<br>' + '<strong>Протяженность маршрута</strong>: ' + graph_data['Протяженность маршрута'] +
                        '<br>' + '<strong>Примерное время прохождения маршрута</strong>: ' + graph_data['Примерное время прохождения маршрута'] +
                        '<br><br>' + '<strong>Отклонения от курсов на участках</strong>: ' + graph_data['Отклонения от курсов на участках'] +
                        '<br>' + '<strong>Скорость на участках</strong>: ' + graph_data['Скорость на участках'] +
                        '<br>' + '<strong>Протяженность участков</strong>: ' + graph_data['Протяженность участков'] +
                        '<br><br>' + '<strong>Характеристики графа</strong>: ' + graph_data['Характеристики графа'] +
                        '<br>' + '<strong>Точки маршрута</strong>: ' + graph_data['Точки маршрута'] +
                        '<br><br>' + '<strong>Время построения графа</strong>: ' + graph_data['Время построения графа'] +
                        '<br>' + '<strong>Время планирования маршрута</strong>: ' + graph_data['Время планирования маршрута'] + '<br>';
                }

                legend.appendChild(item);
                $("#loader").hide();

            },
            error: function (jqXHR, textStatus, errorThrown) {
                $("#loader").hide();
                return alert("Error status: " + textStatus + "\nError thrown: " + errorThrown);
            }
        });
    }
}

//Обработка кнопки "Кластеризовать данные"
function Do_clustering() {
    document.querySelector('.red_text').style.cssText = '';
    // Получаем значения полей ввода
    const fields = ['weight_distance', 'weight_speed', 'weight_course', 'eps', 'min_samples', 'metric_degree', 'hull_type'];
    var parameters_for_DBSCAN = {};
    let allFieldsFilled = true;
    var alert_list = []
    fields.forEach(field => {
        const value = document.getElementById(field).value;
        if (!value) {
            allFieldsFilled = false
            alert_list.push(field);
        }
        parameters_for_DBSCAN[field] = value;
    });

    // Получаем выбранный id датасета
    const selectedDataset = document.querySelector('input[name="dataset_id"]:checked');
    if (!selectedDataset) {
        alert("Пожалуйста, выберите датасет!");
        return;
    }
    parameters_for_DBSCAN['dataset_id'] = selectedDataset.value;

    // Если не все поля заполнены, выходим из функции
    if (!allFieldsFilled) return alert("Остались незаполненные поля: " + alert_list);
    if (!allFieldsFilled) return;

    $("#loader").show();
    $.ajax({
        type: 'POST',
        url: '/post_clustering_parameters',
        contentType: 'application/json',
        data: JSON.stringify(parameters_for_DBSCAN),
        success: function (data) {
            const ClustersLayer = new ol.layer.Image({
                name: 'Clusters',
                visible: false,
                source: new ol.source.ImageStatic({
                    url: data[0][0], // URL PNG-изображения
                    imageSize: [5983, 4143], // Размер изображения
                    projection: projection,
                    imageExtent: extent,
                })
            });
            const PolygonsLayer = new ol.layer.Image({
                name: 'Polygons',
                visible: true,
                source: new ol.source.ImageStatic({
                    url: data[0][1], // URL PNG-изображения
                    imageSize: [5983, 4143], // Размер изображения
                    projection: projection,
                    imageExtent: extent,
                })
            });


            const layers = map.getLayers().getArray();
            layers.forEach(layer => {
                if (layer.get('name') === "Ships") {
                    layer.setVisible(false);
                }
            });

            // Удаляем старые слои с карты
            const names = ["Clusters", "Polygons", "Graph", "StartPoint", "EndPoint"];
            names.forEach(name => {
                const layers = map.getLayers().getArray();
                layers.forEach(layer => {
                    if (layer.get('name') === name) {
                        map.removeLayer(layer);
                    }
                });
            });

            map.addLayer(ClustersLayer);
            map.addLayer(PolygonsLayer);
            document.getElementById("start_coords").value = "";
            document.getElementById("end_coords").value = "";


            //Легенда с данными из вычислительной части
            let clusters_data = data[1];
            let legend = document.getElementById('legend');
            legend.innerHTML = '';
            let item = document.createElement('div');

            item.innerHTML =
                '<strong>Всего кластеров</strong>: ' + clusters_data['Всего кластеров'] +
                '<br>' + '<strong>Доля шума</strong>: ' + clusters_data['Доля шума'] +
                '<br><br>' + '<strong>Время выполнения DBSCAN</strong>: ' + clusters_data['Время выполнения DBSCAN'] + '<br>';
            legend.appendChild(item);

            $("#loader").hide();

        },
        error: function (jqXHR, textStatus, errorThrown) {
            $("#loader").hide();
            return alert("Error status: " + textStatus + "\nError thrown: " + errorThrown);
        }
    });
}

document.getElementsByClassName('ol-attribution ol-unselectable ol-control ol-collapsed')[0].remove()

document.querySelectorAll('details').forEach(details => {
    details.addEventListener('click', e => {
        // Если клик именно на summary или на checkbox — не вмешиваемся
        if (e.target.tagName.toLowerCase() === 'summary' ||
            e.target.tagName.toLowerCase() === 'label' ||
            e.target.tagName.toLowerCase() === 'span' ||
            (e.target.tagName.toLowerCase() === 'input' && e.target.type === 'checkbox') ||
            (e.target.tagName.toLowerCase() === 'input' && e.target.type === 'file') ||
            (e.target.tagName.toLowerCase() === 'input' && e.target.type === 'radio') ||
            (e.target.tagName.toLowerCase() === 'button' && e.target.type === 'submit')) return;

        // Если details закрыт — открываем
        if (!details.open) {
            details.open = true;
        } else {
            // Если открыт — клики в теле игнорируем (не закрываем)
            e.preventDefault();
        }
    });
});

function resizeMap() {
    if (map) {
        map.updateSize(); // Обновляем размер карты
    }
}

window.addEventListener('resize', resizeMap);
window.addEventListener('load', resizeMap);

document.querySelector('.logout-button').addEventListener('click', function () {
    window.location.href = "/logout";
});

document.addEventListener('DOMContentLoaded', function () {
    // --- Переключатель для max_gap_minutes ---
    const interpolationSwitch = document.getElementById('interpolation');
    const maxGapInput = document.getElementById('max_gap_minutes');
    const maxGapLabel = document.getElementById('max_gap_label');
    let lastValue = maxGapInput.value;

    function updateMaxGapState() {
        if (interpolationSwitch.checked) {
            maxGapInput.disabled = false;
            maxGapInput.value = lastValue || 30;
            maxGapLabel.classList.remove('disabled-label');
        } else {
            lastValue = maxGapInput.value;
            maxGapInput.disabled = true;
            maxGapInput.value = '';
            maxGapLabel.classList.add('disabled-label');
        }
    }

    interpolationSwitch.addEventListener('change', updateMaxGapState);
    updateMaxGapState();

    // --- Асинхронная отправка формы создания датасета ---
    document.getElementById('upload-btn').addEventListener('click', function (event) {
        event.preventDefault();

        // Сброс сообщений
        document.getElementById('upload-error').style.display = 'none';
        document.getElementById('upload-success').style.display = 'none';
        document.getElementById('upload-loading').style.display = 'none';

        // Валидация: название датасета не должно быть пустым
        const datasetName = document.getElementById('dataset-name').value.trim();
        if (!datasetName) {
            document.getElementById('upload-error').textContent = 'Поле "Название датасета" обязательно для заполнения!';
            document.getElementById('upload-error').style.display = 'block';
            return;
        }

        // Валидация: оба файла выбраны
        const filePositions = document.getElementById('file-positions').files[0];
        const fileMarine = document.getElementById('file-marine').files[0];
        if (!filePositions || !fileMarine) {
            document.getElementById('upload-error').textContent = 'Пожалуйста, выберите оба файла!';
            document.getElementById('upload-error').style.display = 'block';
            return;
        }

        // Показать "Загрузка..."
        document.getElementById('upload-loading').style.display = 'block';

        // Формируем данные для отправки
        const form = document.getElementById('dataset-upload-form');
        const formData = new FormData(form);

        fetch('/upload_dataset', {
            method: 'POST',
            body: formData
        })
            .then(response => response.json())
            .then(data => {
                document.getElementById('upload-loading').style.display = 'none';
                if (data.success) {
                    document.getElementById('upload-success').textContent = data.message || 'Данные успешно загружены!';
                    document.getElementById('upload-success').style.display = 'block';
                    updateDatasetList();
                } else {
                    document.getElementById('upload-error').textContent = data.message || 'Ошибка загрузки!';
                    document.getElementById('upload-error').style.display = 'block';
                }
            })
            .catch(error => {
                document.getElementById('upload-loading').style.display = 'none';
                document.getElementById('upload-error').textContent = 'Ошибка соединения с сервером!';
                document.getElementById('upload-error').style.display = 'block';
            });
    });
});

let selectedDatasetId = null;

function updateDatasetList() {
    fetch('/get_datasets')
        .then(response => response.json())
        .then(data => {
            // Сохраняем выбранный id (если был выбран)
            if (!selectedDatasetId) {
                // Если еще не выбран, ищем выбранный radio (например, при первой загрузке)
                const checked = document.querySelector('input[name="dataset_id"]:checked');
                if (checked) selectedDatasetId = checked.value;
            }

            // Обновляем "Все"
            const tabAll = document.getElementById('tab-all');
            tabAll.innerHTML = '';
            if (data.all.length === 0) {
                tabAll.innerHTML = '<div>Нет доступных датасетов</div>';
            } else {
                data.all.forEach(ds => {
                    tabAll.innerHTML += `
                        <div class="dataset-option${selectedDatasetId == ds.id ? ' selected' : ''}">
                            <input type="radio" id="ds-all-${ds.id}" name="dataset_id" value="${ds.id}" ${selectedDatasetId == ds.id ? 'checked' : ''}>
                            <label for="ds-all-${ds.id}">${ds.name}</label>
                        </div>`;
                });
            }
            // Обновляем "Мои"
            const tabMine = document.getElementById('tab-mine');
            tabMine.innerHTML = '';
            if (data.mine.length === 0) {
                tabMine.innerHTML = '<div>У вас нет своих датасетов</div>';
            } else {
                data.mine.forEach(ds => {
                    tabMine.innerHTML += `
                        <div class="dataset-option${selectedDatasetId == ds.id ? ' selected' : ''}">
                            <input type="radio" id="ds-mine-${ds.id}" name="dataset_id" value="${ds.id}" ${selectedDatasetId == ds.id ? 'checked' : ''}>
                            <label for="ds-mine-${ds.id}">${ds.name}</label>
                        </div>`;
                });
            }
            // Повторно навешиваем обработчики выделения
            document.querySelectorAll('input[name="dataset_id"]').forEach(function (radio) {
                radio.addEventListener('change', function () {
                    selectedDatasetId = radio.value;
                    // Выделяем выбранный во всех вкладках
                    document.querySelectorAll('.dataset-option').forEach(opt => {
                        const input = opt.querySelector('input[name="dataset_id"]');
                        if (input && input.value === selectedDatasetId) {
                            opt.classList.add('selected');
                            input.checked = true;
                        } else {
                            opt.classList.remove('selected');
                            if (input) input.checked = false;
                        }
                    });
                });
            });
        });
}

function showTab(tab) {
    document.getElementById('tab-all').style.display = tab === 'all' ? '' : 'none';
    document.getElementById('tab-mine').style.display = tab === 'mine' ? '' : 'none';
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector('.tab-btn' + (tab === 'all' ? ':first-child' : ':last-child')).classList.add('active');
}

document.addEventListener('DOMContentLoaded', function () {
    // Сохраняем выбранный id при первом выборе
    document.querySelectorAll('input[name="dataset_id"]').forEach(function (radio) {
        radio.addEventListener('change', function () {
            selectedDatasetId = radio.value;
            document.querySelectorAll('.dataset-option').forEach(opt => {
                const input = opt.querySelector('input[name="dataset_id"]');
                if (input && input.value === selectedDatasetId) {
                    opt.classList.add('selected');
                    input.checked = true;
                } else {
                    opt.classList.remove('selected');
                    if (input) input.checked = false;
                }
            });
        });
        // Если radio уже выбран при загрузке
        if (radio.checked) selectedDatasetId = radio.value;
    });

    // AJAX submit формы
    document.getElementById('dataset-form').addEventListener('submit', function (event) {
        event.preventDefault();
        document.getElementById('dataset-error').style.display = 'none';
        document.getElementById('dataset-success').style.display = 'none';

        const selected = document.querySelector('input[name="dataset_id"]:checked');
        if (!selected) {
            document.getElementById('dataset-error').textContent = 'Пожалуйста, выберите датасет!';
            document.getElementById('dataset-error').style.display = 'block';
            return;
        }
        selectedDatasetId = selected.value;

        fetch('/choose_dataset', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: 'dataset_id=' + encodeURIComponent(selected.value)
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('dataset-success').textContent = data.message;
                    document.getElementById('dataset-success').style.display = 'block';
                } else {
                    document.getElementById('dataset-error').textContent = data.message || 'Ошибка!';
                    document.getElementById('dataset-error').style.display = 'block';
                }
            })
            .catch(() => {
                document.getElementById('dataset-error').textContent = 'Ошибка соединения с сервером!';
                document.getElementById('dataset-error').style.display = 'block';
            });
    });
});