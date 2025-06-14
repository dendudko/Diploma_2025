/**
 * Вспомогательная функция для асинхронного создания слоя с изображением.
 */
function createImageLayer(options) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = function () {
            const layer = new ol.layer.Image({
                name: options.name,
                visible: options.visible !== undefined ? options.visible : true,
                opacity: options.opacity !== undefined ? options.opacity : 1.0,
                source: new ol.source.ImageStatic({
                    url: options.url,
                    imageSize: [this.width, this.height],
                    projection: options.projection,
                    imageExtent: options.imageExtent,
                })
            });
            resolve(layer);
        };
        image.onerror = function () {
            console.error(`Не удалось загрузить изображение для слоя "${options.name}" по URL: ${options.url}`);
            reject(new Error(`Image load error for ${options.name}`));
        };
        image.src = options.url;
    });
}


/**
 * =============================================================================
 *                      ОСНОВНАЯ ЛОГИКА ИНИЦИАЛИЗАЦИИ КАРТЫ
 * =============================================================================
 */

const backgroundImageUrl = '/static/images/bg/background.png';
// const geographicExtent = [15522946.393668033, 5002641.018067474, 15751596.627757415, 5160979.444049783];
let geographicExtent = [15538419.802888298, 5003643.068442375, 15751596.627757415, 5160889.56738335];
const backgroundImage = new Image();

backgroundImage.onload = function () {
    const imageWidth = this.width;
    const imageHeight = this.height;

    const pixelExtent = [0, 0, imageWidth, imageHeight];
    const pixelProjection = new ol.proj.Projection({
        code: 'custom-pixel-map',
        units: 'pixels',
        extent: pixelExtent,
    });

    const map = new ol.Map({
        target: 'map',
        pixelRatio: 2,
        layers: [
            new ol.layer.Image({
                name: 'Background',
                source: new ol.source.ImageStatic({
                    url: backgroundImageUrl,
                    projection: pixelProjection,
                    imageExtent: pixelExtent,
                }),
                opacity: 0.2
            }),
        ],
        view: new ol.View({
            projection: pixelProjection,
            center: ol.extent.getCenter(pixelExtent),
            zoom: 2,
            minZoom: 2,
            maxZoom: 4,
            extent: pixelExtent
        }),
        controls: ol.control.defaults.defaults({attribution: false}).extend([
            new ol.control.FullScreen(),
            new ol.control.ZoomToExtent({extent: pixelExtent})
        ])
    });

    map.addControl(new ol.control.LayerSwitcher({reverse: false}));

    // --- Легенда ---
    let legendShown = false;
    const legendElement = document.getElementById('legend');
    const legendButton = new ol.control.Button({
        className: 'ol-legend ol-unselectable ol-control ol-collapsed',
        title: 'Данные работы алгоритма',
        handleClick: function () {
            legendShown = !legendShown;
            legendElement.className = legendShown ? 'show' : 'hide';
        },
    });
    map.addControl(legendButton);
    map.getViewport().appendChild(legendElement);

    // --- Управление курсором ---
    map.getViewport().style.cursor = "auto";
    map.on('pointerdrag', () => {
        map.getViewport().style.cursor = "grabbing";
    });
    map.on('pointerup', () => {
        map.getViewport().style.cursor = "auto";
    });

    /**
     * Преобразует пиксельные координаты в географические (Mercator).
     */
    function pixelToMercator(pixelCoord) {
        const [px, py] = pixelCoord;
        const [p_x1, p_y1, p_x2, p_y2] = pixelExtent;
        const [g_x1, g_y1, g_x2, g_y2] = geographicExtent;
        const x_ratio = (g_x2 - g_x1) / (p_x2 - p_x1);
        const y_ratio = (g_y2 - g_y1) / (p_y2 - p_y1);
        return [g_x1 + (px * x_ratio), g_y1 + (py * y_ratio)];
    }

    /**
     * Преобразует географические координаты (Lon/Lat) в пиксельные.
     */
    function geoToPixel(lon, lat) {
        const mercatorCoord = ol.proj.fromLonLat([lon, lat]);
        const [mx, my] = mercatorCoord;
        const [p_x1, p_y1, p_x2, p_y2] = pixelExtent;
        const [g_x1, g_y1, g_x2, g_y2] = geographicExtent;
        const x_ratio = (p_x2 - p_x1) / (g_x2 - g_x1);
        const y_ratio = (p_y2 - p_y1) / (g_y2 - g_y1);
        return [(mx - g_x1) * x_ratio, (my - g_y1) * y_ratio];
    }

    // --- ЛОГИКА УСТАНОВКИ ТОЧЕК ---
    function setPoints() {
        const startPointInput = document.getElementById("start_coords");
        const endPointInput = document.getElementById("end_coords");
        const pickStartBtn = document.getElementById("pick-start-btn");
        const pickEndBtn = document.getElementById("pick-end-btn");
        let pickingFor = null; // null, 'start', или 'end'

        function updateMarker(type, pixelCoord) {
            const layerName = type === 'start' ? 'StartPoint' : 'EndPoint';
            const iconSrc = type === 'start' ? '/static/images/markers/start_point.png' : '/static/images/markers/end_point.png';
            map.getLayers().getArray().filter(l => l.get('name') === layerName).forEach(l => map.removeLayer(l));
            const pointLayer = new ol.layer.Vector({
                name: layerName,
                source: new ol.source.Vector({features: [new ol.Feature({geometry: new ol.geom.Point(pixelCoord)})]}),
                style: new ol.style.Style({image: new ol.style.Icon({anchor: [0.5, 1], scale: 0.07, src: iconSrc})})
            });
            map.addLayer(pointLayer);
        }

        pickStartBtn.addEventListener('click', () => {
            pickingFor = 'start';
            map.getViewport().style.cursor = 'crosshair';
        });
        pickEndBtn.addEventListener('click', () => {
            pickingFor = 'end';
            map.getViewport().style.cursor = 'crosshair';
        });

        function handleTextInput(event) {
            const inputType = event.target.id === 'start_coords' ? 'start' : 'end';
            const parts = event.target.value.replace(/,/g, ' ').split(/\s+/).filter(Boolean);
            if (parts.length !== 2) return;
            const lat = parseFloat(parts[0]);
            const lon = parseFloat(parts[1]);
            if (!isNaN(lat) && !isNaN(lon)) {
                const pixelCoord = geoToPixel(lon, lat);
                updateMarker(inputType, pixelCoord);
            }
        }

        startPointInput.addEventListener('change', handleTextInput);
        endPointInput.addEventListener('change', handleTextInput);

        map.on('click', function (evt) {
            const hasDataLayers = map.getLayers().getArray().some(l => ['Polygons', 'Graph'].includes(l.get('name')) && l.getVisible());
            if (!pickingFor) return;
            if (!hasDataLayers) {
                alert("Координаты можно указывать только после кластеризации данных.");
                pickingFor = null;
                map.getViewport().style.cursor = 'auto';
                return;
            }
            const pixelCoordinate = evt.coordinate;
            const mercatorCoordinate = pixelToMercator(pixelCoordinate);
            const geoCoordinate = ol.proj.toLonLat(mercatorCoordinate);
            const coordsString = `${geoCoordinate[1].toFixed(6)}, ${geoCoordinate[0].toFixed(6)}`;
            if (pickingFor === 'start') {
                startPointInput.value = coordsString;
                updateMarker('start', pixelCoordinate);
            } else if (pickingFor === 'end') {
                endPointInput.value = coordsString;
                updateMarker('end', pixelCoordinate);
            }
            pickingFor = null;
            map.getViewport().style.cursor = 'auto';
        });
    }

    setPoints();

    // --- Обработка кнопки "Построить граф и проложить маршрут" ---
    async function createGraph() {
        if (!map.getLayers().getArray().some(l => l.get('name') === 'Polygons')) {
            document.getElementById('do_cluster').style.cssText = 'box-shadow: 0px 0px 3px 3px #91B44AB2;';
            return alert("Сначала необходимо кластеризовать данные");
        }
        const fields = ['distance_delta', 'weight_func_degree', 'angle_of_vision', 'weight_time_graph', 'weight_course_graph', 'search_algorithm', 'start_coords', 'end_coords'];
        const parameters = {'points_inside': $('#points_inside').is(':checked')};
        fields.forEach(id => {
            parameters[id] = document.getElementById(id).value;
        });
        const emptyFields = fields.filter(id => !parameters[id]);
        if (emptyFields.length > 0) return alert("Остались незаполненные поля: " + emptyFields.join(', '));
        if (parameters['start_coords'] === parameters['end_coords']) return alert("Упс! Начальная точка совпадает с конечной.");
        const selectedDataset = document.querySelector('input[name="dataset_id"]:checked');
        if (!selectedDataset) return alert("Пожалуйста, выберите датасет!");
        parameters['dataset_id'] = selectedDataset.value;
        $("#loader").show();
        try {
            const data = await $.ajax({
                type: 'POST',
                url: '/post_graphs_parameters',
                contentType: 'application/json',
                data: JSON.stringify(parameters)
            });
            geographicExtent = data[2];
            map.getLayers().getArray().filter(l => l.get('name') === 'Graph').forEach(l => map.removeLayer(l));
            const graphLayer = await createImageLayer({
                name: 'Graph',
                url: data[0],
                projection: pixelProjection,
                imageExtent: pixelExtent
            });
            map.addLayer(graphLayer);
            const backgroundLayer = map.getLayers().getArray().find(l => l.get('name') === 'Background');
            if (backgroundLayer) backgroundLayer.setVisible(false);
            ['StartPoint', 'EndPoint'].forEach(name => {
                const layer = map.getLayers().getArray().find(l => l.get('name') === name);
                if (layer) {
                    map.removeLayer(layer);
                    map.addLayer(layer);
                }
            });
            map.getLayers().getArray().filter(l => ["Clusters", "Polygons", "Ships"].includes(l.get('name'))).forEach(l => l.setVisible(false));
            legendElement.innerHTML = '';
            const item = document.createElement('div');
            const graph_data = data[1];
            item.innerHTML = 'Error' in graph_data ? `<strong>${graph_data['Error']}</strong><br>` : Object.entries(graph_data).map(([key, value]) => `<strong>${key}</strong>: ${value}<br>`).join('');
            legendElement.appendChild(item);
        } catch (error) {
            const errorMessage = error.responseJSON?.error || error.statusText || "Неизвестная ошибка";
            alert(`Ошибка: ${errorMessage}`);
        } finally {
            $("#loader").hide();
        }
    }

    // --- Обработка кнопки "Кластеризовать данные" ---
    async function doClustering() {
        document.querySelector('.red_text').style.cssText = '';
        const fields = ['weight_distance', 'weight_speed', 'weight_course', 'eps', 'min_samples', 'metric_degree', 'hull_type'];
        const parameters = {};
        fields.forEach(id => {
            parameters[id] = document.getElementById(id).value;
        });
        const emptyFields = fields.filter(id => !parameters[id]);
        const selectedDataset = document.querySelector('input[name="dataset_id"]:checked');
        if (!selectedDataset) return alert("Пожалуйста, выберите датасет!");
        parameters['dataset_id'] = selectedDataset.value;
        if (emptyFields.length > 0) return alert("Остались незаполненные поля: " + emptyFields.join(', '));
        $("#loader").show();
        try {
            const data = await $.ajax({
                type: 'POST',
                url: '/post_clustering_parameters',
                contentType: 'application/json',
                data: JSON.stringify(parameters)
            });
            geographicExtent = data[2];
            const [clustersLayer, polygonsLayer] = await Promise.all([
                createImageLayer({
                    name: 'Clusters',
                    url: data[0][0],
                    visible: false,
                    projection: pixelProjection,
                    imageExtent: pixelExtent
                }),
                createImageLayer({
                    name: 'Polygons',
                    url: data[0][1],
                    visible: true,
                    projection: pixelProjection,
                    imageExtent: pixelExtent
                })
            ]);
            map.getLayers().getArray().filter(l => ["Clusters", "Polygons", "Graph", "StartPoint", "EndPoint", "Ships"].includes(l.get('name'))).forEach(l => map.removeLayer(l));
            map.addLayer(clustersLayer);
            map.addLayer(polygonsLayer);
            const backgroundLayer = map.getLayers().getArray().find(l => l.get('name') === 'Background');
            if (backgroundLayer) backgroundLayer.setVisible(false);
            document.getElementById("start_coords").value = "";
            document.getElementById("end_coords").value = "";
            legendElement.innerHTML = '';
            const item = document.createElement('div');
            item.innerHTML = Object.entries(data[1]).map(([key, value]) => `<strong>${key}</strong>: ${value}<br>`).join('');
            legendElement.appendChild(item);
        } catch (error) {
            alert(`Ошибка при кластеризации: ${error.statusText || 'Проверьте консоль'}`);
        } finally {
            $("#loader").hide();
        }
    }

    document.getElementById('do_graph').addEventListener('click', createGraph);
    document.getElementById('do_cluster').addEventListener('click', doClustering);
    window.addEventListener('resize', () => map.updateSize());
};

backgroundImage.onerror = () => {
    console.error("Не удалось загрузить фоновое изображение. Карта не будет инициализирована.");
    document.getElementById('map').innerHTML = '<div style="padding: 20px; text-align: center; color: red;">Ошибка загрузки карты.</div>';
};
backgroundImage.src = backgroundImageUrl;

/**
 * =============================================================================
 *                      ЛОГИКА UI (НЕ ЗАВИСЯЩАЯ ОТ КАРТЫ)
 * =============================================================================
 */
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('details').forEach(details => {
        details.addEventListener('click', e => {
            if (e.target.closest('summary, label, input, button, a')) return;
            if (!details.open) details.open = true;
            else e.preventDefault();
        });
    });

    document.querySelector('.logout-button')?.addEventListener('click', () => {
        window.location.href = "/logout";
    });

    const interpolationSwitch = document.getElementById('interpolation');
    if (interpolationSwitch) {
        const maxGapInput = document.getElementById('max_gap_minutes');
        const maxGapLabel = document.getElementById('max_gap_label');
        let lastValue = maxGapInput.value;
        const updateMaxGapState = () => {
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
        };
        interpolationSwitch.addEventListener('change', updateMaxGapState);
        updateMaxGapState();
    }

    const uploadBtn = document.getElementById('upload-btn');
    if (uploadBtn) {
        uploadBtn.addEventListener('click', function (event) {
            event.preventDefault();
            const errorEl = document.getElementById('upload-error'),
                successEl = document.getElementById('upload-success'),
                loadingEl = document.getElementById('upload-loading');
            [errorEl, successEl, loadingEl].forEach(el => el.style.display = 'none');
            if (!document.getElementById('dataset-name').value.trim()) {
                errorEl.textContent = 'Поле "Название датасета" обязательно для заполнения!';
                return errorEl.style.display = 'block';
            }
            if (!document.getElementById('file-positions').files[0] || !document.getElementById('file-marine').files[0]) {
                errorEl.textContent = 'Пожалуйста, выберите оба файла!';
                return errorEl.style.display = 'block';
            }
            loadingEl.style.display = 'block';
            const formData = new FormData(document.getElementById('dataset-upload-form'));
            fetch('/upload_dataset', {method: 'POST', body: formData})
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        successEl.textContent = data.message || 'Данные успешно загружены!';
                        successEl.style.display = 'block';
                        updateDatasetList();
                    } else {
                        errorEl.textContent = data.message || 'Ошибка загрузки!';
                        errorEl.style.display = 'block';
                    }
                })
                .catch(() => {
                    errorEl.textContent = 'Ошибка соединения с сервером!';
                    errorEl.style.display = 'block';
                })
                .finally(() => {
                    loadingEl.style.display = 'none';
                });
        });
    }

    let selectedDatasetId = document.querySelector('input[name="dataset_id"]:checked')?.value || null;

    /**
     * Принудительно синхронизирует UI (класс .selected) с текущим состоянием (selectedDatasetId).
     */
    const highlightSelectedDataset = () => {
        document.querySelectorAll('.dataset-option').forEach(opt => {
            const input = opt.querySelector('input[name="dataset_id"]');
            if (input) {
                const isSelected = input.value === selectedDatasetId;
                opt.classList.toggle('selected', isSelected);
                if (isSelected) {
                    input.checked = true;
                }
            }
        });
    };

    /**
     * Привязывает обработчики к radio-кнопкам.
     */
    const attachDatasetHandlers = () => {
        document.querySelectorAll('input[name="dataset_id"]').forEach(radio => {
            radio.addEventListener('change', () => {
                selectedDatasetId = radio.value;
                highlightSelectedDataset();
            });
        });
    };

    /**
     * Обновляет список датасетов с сервера, генерируя УНИФИЦИРОВАННЫЙ HTML.
     */
    const updateDatasetList = () => {
        fetch('/get_datasets')
            .then(res => res.json())
            .then(data => {
                const renderList = (container, datasets) => {
                    if (datasets.length === 0) {
                        container.innerHTML = `<div>${container.id === 'tab-all' ? 'Нет доступных датасетов' : 'У вас нет своих датасетов'}</div>`;
                        return;
                    }
                    container.innerHTML = datasets.map(ds => {
                        const deleteButtonHtml = (container.id === 'tab-mine')
                            ? `<button type="button" class="delete-dataset-btn" data-dataset-id="${ds.id}" title="Удалить датасет">&#10060;</button>`
                            : '';

                        return `
                            <div class="dataset-option">
                                <div class="dataset-info">
                                    <input type="radio" id="ds-${container.id}-${ds.id}" name="dataset_id" value="${ds.id}">
                                    <label for="ds-${container.id}-${ds.id}">${ds.name}</label>
                                </div>
                                ${deleteButtonHtml}
                            </div>`;
                    }).join('');
                };

                renderList(document.getElementById('tab-all'), data.all);
                renderList(document.getElementById('tab-mine'), data.mine);

                attachDatasetHandlers();
                highlightSelectedDataset();
            });
    };

    /**
     * Переключает видимость вкладок.
     */
    window.showTab = (tab) => {
        document.getElementById('tab-all').style.display = tab === 'all' ? '' : 'none';
        document.getElementById('tab-mine').style.display = tab === 'mine' ? '' : 'none';
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelector(`.tab-btn[onclick*="'${tab}'"]`).classList.add('active');

        // Принудительно обновляем подсветку при смене вкладки
        highlightSelectedDataset();
    };

    const datasetForm = document.getElementById('dataset-form');
    if (datasetForm) {
        datasetForm.addEventListener('submit', function (event) {
            event.preventDefault();
            const errorEl = document.getElementById('dataset-error'),
                successEl = document.getElementById('dataset-success');
            [errorEl, successEl].forEach(el => el.style.display = 'none');
            const selected = document.querySelector('input[name="dataset_id"]:checked');
            if (!selected) {
                errorEl.textContent = 'Пожалуйста, выберите датасет!';
                return errorEl.style.display = 'block';
            }
            fetch('/choose_dataset', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest'},
                body: 'dataset_id=' + encodeURIComponent(selected.value)
            })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        successEl.textContent = data.message;
                        successEl.style.display = 'block';
                    } else {
                        errorEl.textContent = data.message || 'Ошибка!';
                        errorEl.style.display = 'block';
                    }
                })
                .catch(() => {
                    errorEl.textContent = 'Ошибка соединения с сервером!';
                    errorEl.style.display = 'block';
                });
        });
    }

    attachDatasetHandlers();
    highlightSelectedDataset();
    showTab('all');

    document.body.addEventListener('click', function (event) {
        if (event.target.matches('.delete-dataset-btn')) {
            event.preventDefault();
            const button = event.target;
            const datasetId = button.dataset.datasetId;
            const datasetOptionDiv = button.closest('.dataset-option');
            const datasetName = datasetOptionDiv.querySelector('label').textContent;

            if (confirm(`Вы уверены, что хотите удалить датасет "${datasetName}"? Это действие необратимо.`)) {

                const loadingEl = document.getElementById('dataset-loading');
                const errorEl = document.getElementById('dataset-error');
                const successEl = document.getElementById('dataset-success');

                errorEl.style.display = 'none';
                successEl.style.display = 'none';
                loadingEl.style.display = 'block';

                fetch('/delete_dataset', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                    body: JSON.stringify({id: datasetId})
                })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            successEl.textContent = data.message || 'Датасет успешно удален.';
                            successEl.style.display = 'block';
                            updateDatasetList();
                        } else {
                            errorEl.textContent = data.message || 'Не удалось удалить датасет.';
                            errorEl.style.display = 'block';
                        }
                    })
                    .catch(error => {
                        console.error('Ошибка при удалении датасета:', error);
                        errorEl.textContent = 'Ошибка соединения с сервером.';
                        errorEl.style.display = 'block';
                    })
                    .finally(() => {
                        loadingEl.style.display = 'none';
                    });
            }
        }
    });

    document.querySelectorAll('.file-input-hidden').forEach(function (input) {
        const label = input.nextElementSibling;
        const buttonSpan = label.querySelector('.file-upload-button');
        const fileNameSpan = label.querySelector('.file-name');
        const originalButtonText = buttonSpan.textContent;

        input.addEventListener('change', function (event) {
            if (event.target.files.length > 0) {
                fileNameSpan.textContent = event.target.files[0].name;
                buttonSpan.textContent = 'Файл выбран';
                label.classList.add('file-chosen');
            } else {
                fileNameSpan.textContent = 'Файл не выбран';
                buttonSpan.textContent = originalButtonText;
                label.classList.remove('file-chosen');
            }
        });
    });
});
