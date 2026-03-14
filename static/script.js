let currentCategory = 'home';
let currentPath = '';
let currentSelectedFile = null;

function formatBytes(bytes) {
    if (!+bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

function getExt(filename) { return filename.split('.').pop().toLowerCase(); }
function isImage(filename) { return ['jpg','jpeg','png','gif','webp','bmp','svg'].includes(getExt(filename)); }
function isPdf(filename) { return getExt(filename) === 'pdf'; }
function isVideo(filename) { return ['mp4','webm','ogg','mov'].includes(getExt(filename)); }
function isAudio(filename) { return ['mp3','wav','ogg','flac','m4a'].includes(getExt(filename)); }
function isText(filename) { return ['txt','html','css','js','py','json','md','csv'].includes(getExt(filename)); }

function updateBreadcrumb() {
    const bc = document.getElementById('breadcrumb');
    const divider = document.getElementById('breadcrumb-divider');
    if (!bc || !divider) return;
    
    if (currentCategory !== 'home' && currentCategory !== 'trash') {
        bc.innerHTML = '';
        divider.style.display = 'none';
        return;
    }
    
    divider.style.display = 'block';
    let rootName = currentCategory === 'home' ? '🏠 홈' : '🗑️ 휴지통';
    let html = `<div class="breadcrumb-item" onclick="navigate('')">${rootName}</div>`;
    
    if (currentPath) {
        const parts = currentPath.split('/');
        let agg = '';
        parts.forEach((p) => {
            agg += (agg ? '/' : '') + p;
            html += `<span style="color:var(--text-secondary); margin: 0 4px; font-weight: bold;">/</span><div class="breadcrumb-item" onclick="navigate('${agg}')">${p}</div>`;
        });
    }
    bc.innerHTML = html;
}

function navigate(path) {
    currentPath = path;
    loadFiles(currentCategory);
}

function loadFiles(category = 'home') {
    if (currentCategory !== category) {
        currentPath = '';
    }
    currentCategory = category;
    
    document.getElementById('category-title').textContent = 
        category === 'home' ? '내 클라우드' : 
        category === 'recent' ? '최근 항목' : 
        category === 'important' ? '중요 문서' : '휴지통';

    document.querySelectorAll('.menu-item').forEach(el => el.classList.remove('active'));
    document.getElementById(`menu-${category}`).classList.add('active');

    updateBreadcrumb();

    fetch(`/api/files?category=${category}&path=${encodeURIComponent(currentPath)}`)
        .then(res => res.json())
        .then(files => {
            const grid = document.getElementById('file-grid');
            if(!grid) return;
            grid.innerHTML = '';
            
            files.forEach(file => {
                const el = document.createElement('div');
                el.className = 'file-card';
                
                let iconContent = '📄';
                if (file.type === 'folder') iconContent = '<span style="font-size:42px; color:#ffd43b">📁</span>';
                else if (isImage(file.name)) iconContent = `<img src="${file.url}" style="width:100%; height:100%; object-fit:cover;">`;
                else if (isPdf(file.name)) iconContent = '<span style="color:#ff6b6b">📕</span>';
                else if (isVideo(file.name)) iconContent = '<span style="color:#4dabf7">🎬</span>';
                else if (isAudio(file.name)) iconContent = '<span style="color:#fcc419">🎵</span>';
                else if (isText(file.name)) iconContent = '<span style="color:#51cf66">📝</span>';

                const displayName = file.name;

                el.innerHTML = `
                    <button class="star-btn ${file.is_important ? 'active' : ''}" onclick="toggleStar(event, '${file.path}')">★</button>
                    <div class="file-icon-wrapper">${iconContent}</div>
                    <div class="file-name-text" title="${displayName}">${displayName}</div>
                `;
                
                el.onclick = () => selectFile(file, el);
                el.ondblclick = () => {
                    if (file.type === 'folder') {
                        navigate(file.path);
                    }
                };
                el.oncontextmenu = (e) => showContextMenu(e, file, el);
                grid.appendChild(el);
            });
        });
}

function selectFile(file, element) {
    document.querySelectorAll('.file-card').forEach(el => el.classList.remove('selected'));
    if(element) element.classList.add('selected');
    currentSelectedFile = file;
    
    document.getElementById('detail-name').textContent = file.name;
    document.getElementById('detail-size').textContent = file.type === 'folder' ? formatBytes(file.size) + ' (전체)' : formatBytes(file.size);
    
    const previewBox = document.getElementById('preview-box');
    if (file.type === 'folder') {
        previewBox.innerHTML = `<span style="font-size:64px;">📁</span>`;
    } else if (isImage(file.name)) {
        previewBox.innerHTML = `<img src="${file.url}">`;
        fetch(file.url); 
    } else if (isPdf(file.name)) {
        previewBox.innerHTML = `<iframe src="${file.url}"></iframe>`;
        fetch(file.url);
    } else if (isVideo(file.name)) {
        previewBox.innerHTML = `<video src="${file.url}" controls style="width:100%; max-height:100%;"></video>`;
        fetch(file.url);
    } else if (isAudio(file.name)) {
        previewBox.innerHTML = `<audio src="${file.url}" controls style="width:90%;"></audio>`;
        fetch(file.url);
    } else if (isText(file.name)) {
        previewBox.innerHTML = `<div style="width:100%; height:100%; overflow:auto; padding:10px; background:#1e1e1e; color:#d4d4d4; font-family:monospace; font-size:12px; text-align:left; box-sizing:border-box; white-space:pre-wrap;" id="text-preview">로딩 중...</div>`;
        fetch(file.url).then(r => r.text()).then(txt => {
            const el = document.getElementById('text-preview');
            if(el) el.textContent = txt;
        });
    } else {
        previewBox.innerHTML = `<span style="color:var(--text-secondary); font-size:12px;">미리보기 지원 안됨</span>`;
        fetch(file.url);
    }
}

function updateQuota() {
    fetch('/api/quota')
        .then(res => res.json())
        .then(data => {
            const textEl = document.getElementById('quota-text');
            const fillEl = document.getElementById('quota-fill');
            if(textEl && fillEl) {
                textEl.textContent = `${formatBytes(data.used)} / ${formatBytes(data.total)}`;
                fillEl.style.width = `${data.percent}%`;
            }
        });
}

function toggleUploadMenu() {
    document.getElementById('upload-dropdown').classList.toggle('show');
}

window.onclick = function(event) {
    if (!event.target.closest('#upload-btn-container')) {
        const dropdown = document.getElementById('upload-dropdown');
        if(dropdown) dropdown.classList.remove('show');
    }
    if (!event.target.closest('.context-menu')) {
        const cMenu = document.getElementById('context-menu');
        if(cMenu) cMenu.style.display = 'none';
    }
}

function triggerUpload(isFolder = false) {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    if(isFolder) {
        input.webkitdirectory = true;
    }
    
    input.onchange = async e => {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;

        let progressContainer = document.getElementById('upload-progress-container');
        if (!progressContainer) {
            progressContainer = document.createElement('div');
            progressContainer.id = 'upload-progress-container';
            progressContainer.style.cssText = 'position:fixed; bottom:20px; right:20px; background:var(--bg-secondary); padding:15px; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.3); z-index:9999; min-width:250px;';
            progressContainer.innerHTML = `
                <div style="margin-bottom: 8px; font-size: 14px; color: var(--text-primary); display: flex; justify-content: space-between;">
                    <span id="upload-progress-text">업로드 중...</span>
                    <span id="upload-progress-percent">0%</span>
                </div>
                <div style="width: 100%; height: 10px; background: var(--bg-primary); border-radius: 5px; overflow: hidden;">
                    <div id="upload-progress-bar" style="width: 0%; height: 100%; background: var(--accent); transition: width 0.2s;"></div>
                </div>
            `;
            document.body.appendChild(progressContainer);
        }

        const progressBar = document.getElementById('upload-progress-bar');
        const progressPercent = document.getElementById('upload-progress-percent');
        const progressText = document.getElementById('upload-progress-text');
        progressContainer.style.display = 'block';

        const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
        let uploadedBytes = 0;

        const chunkSize = 20;
        let errorMessage = '';

        for (let i = 0; i < files.length; i += chunkSize) {
            const chunk = files.slice(i, i + chunkSize);
            const formData = new FormData();
            
            chunk.forEach(file => {
                formData.append('files', file);
                let relative = file.webkitRelativePath || file.name;
                if (currentPath) {
                    relative = currentPath + '/' + relative;
                }
                formData.append('paths', relative);
            });

            try {
                await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', '/api/upload');
                    
                    let lastChunkUploaded = 0;
                    
                    xhr.upload.onprogress = (event) => {
                        if (event.lengthComputable) {
                            const chunkUploaded = event.loaded;
                            const currentTotalUploaded = uploadedBytes + chunkUploaded;
                            let percent = Math.floor((currentTotalUploaded / totalBytes) * 100);
                            if(percent > 100) percent = 100;
                            
                            progressBar.style.width = percent + '%';
                            progressPercent.textContent = percent + '%';
                            progressText.textContent = '업로드 중...';
                            
                            lastChunkUploaded = chunkUploaded;
                        }
                    };
                    
                    xhr.onload = () => {
                        if (xhr.status >= 200 && xhr.status < 300) {
                            uploadedBytes += lastChunkUploaded || chunk.reduce((sum, f) => sum + f.size, 0);
                            resolve();
                        } else {
                            let err = '서버 오류 (' + xhr.status + ')';
                            try {
                                const res = JSON.parse(xhr.responseText);
                                if(res.error) err = res.error;
                            } catch(e) {}
                            reject(new Error(err));
                        }
                    };
                    
                    xhr.onerror = () => reject(new Error('네트워크 오류가 발생했습니다.'));
                    xhr.send(formData);
                });
            } catch (err) {
                errorMessage = err.message;
                break;
            }
        }

        setTimeout(() => {
            progressContainer.style.display = 'none';
            progressBar.style.width = '0%';
            progressPercent.textContent = '0%';
        }, 2000);

        if (errorMessage) {
            if(errorMessage.includes('할당된 용량을 초과')) {
                alert('업로드 실패: 저장 공간이 부족합니다. (할당된 용량 초과)');
            } else {
                alert('업로드 실패: ' + errorMessage);
            }
        }
        
        loadFiles(currentCategory);
        updateQuota();
    };
    input.click();
}

function downloadSelected() {
    if (currentSelectedFile && !currentSelectedFile.is_trashed) {
        if (currentSelectedFile.type === 'folder') {
            alert('폴더 전체 다운로드는 지원하지 않습니다. 파일만 다운로드 가능합니다.');
        } else {
            window.open(currentSelectedFile.url, '_blank');
        }
    }
}

function toggleStar(e, filePath) {
    if(e) e.stopPropagation();
    const targetPath = filePath || (currentSelectedFile ? currentSelectedFile.path : null);
    if(!targetPath) return;

    fetch('/api/file/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'toggle_star', filename: targetPath})
    }).then(() => loadFiles(currentCategory));
}

function showContextMenu(e, file, element) {
    e.preventDefault();
    selectFile(file, element);
    
    const menu = document.getElementById('context-menu');
    menu.style.display = 'block';
    menu.style.left = `${e.pageX}px`;
    menu.style.top = `${e.pageY}px`;

    if (file.type === 'folder') {
        menu.innerHTML = `
            <div class="context-menu-item" onclick="navigate('${file.path}')">폴더 열기</div>
            <div class="context-menu-item" onclick="toggleStar(null, '${file.path}')">중요 표시 지정/해제</div>
            <div class="context-divider"></div>
            ${file.is_trashed 
                ? `<div class="context-menu-item" onclick="performAction('restore', '${file.path}')">복원하기</div>
                   <div class="context-menu-item text-danger" onclick="performAction('delete_permanent', '${file.path}')">영구 삭제</div>`
                : `<div class="context-menu-item text-danger" onclick="trashFile('${file.path}')">삭제 (휴지통)</div>`
            }
        `;
    } else {
        menu.innerHTML = `
            <div class="context-menu-item" onclick="downloadSelected()">보기 / 다운로드</div>
            <div class="context-menu-item" onclick="toggleStar(null, '${file.path}')">중요 문서 지정/해제</div>
            <div class="context-divider"></div>
            ${file.is_trashed 
                ? `<div class="context-menu-item" onclick="performAction('restore', '${file.path}')">복원하기</div>
                   <div class="context-menu-item text-danger" onclick="performAction('delete_permanent', '${file.path}')">영구 삭제</div>`
                : `<div class="context-menu-item text-danger" onclick="trashFile('${file.path}')">삭제 (휴지통)</div>`
            }
        `;
    }
}

function trashFile(filePath) {
    const days = prompt("보관 기한(일)을 입력하세요. 이 기간 후 영구 삭제됩니다.", "1");
    if(days !== null && !isNaN(days)) {
        fetch('/api/file/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'trash', filename: filePath, expiry: parseInt(days)})
        }).then(() => {
            loadFiles(currentCategory);
            updateQuota();
        });
    }
}

function performAction(action, filePath) {
    fetch('/api/file/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: action, filename: filePath})
    }).then(() => {
        loadFiles(currentCategory);
        updateQuota();
    });
}

document.addEventListener('DOMContentLoaded', () => {
    if(document.getElementById('file-grid')) {
        loadFiles('home');
        updateQuota();
    }
});