'use strict';

// 서브디렉토리 베이스 경로 (app.php에서 주입, 없으면 빈 문자열)
const BASE = window.BASE || '';

function downloadTemplate(url) {
    window.location.href = BASE + url;
}

// ============================================================
// 유틸리티
// ============================================================

function fmt(v)       { return v ?? '-'; }
function fmtDate(v)   { return v ? String(v).replace('T',' ').slice(0,16) : '-'; }
function fmtDateOnly(v){ return v ? String(v).slice(0,10) : '-'; }

async function apiFetch(url, opts = {}) {
    const res = await fetch(BASE + url, { headers:{'Content-Type':'application/json'}, ...opts });
    if (res.status === 401) { window.location.href = BASE + '/login'; return null; }
    return res;
}

function showToast(msg, type = 'success') {
    const el = document.getElementById('appToast');
    el.className = `toast align-items-center border-0 text-white ${type === 'success' ? 'bg-success' : 'bg-danger'}`;
    document.getElementById('toastMsg').textContent = msg;
    bootstrap.Toast.getOrCreateInstance(el, {delay:3000}).show();
}

let _deleteCb = null;
function confirmDelete(msg, cb) {
    document.getElementById('deleteModalMsg').textContent = msg;
    _deleteCb = cb;
    bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteModal')).show();
}
document.getElementById('deleteConfirmBtn').addEventListener('click', async () => {
    if (_deleteCb) { await _deleteCb(); _deleteCb = null; }
    bootstrap.Modal.getInstance(document.getElementById('deleteModal'))?.hide();
});

function populateSelect(id, items, val, label, placeholder='선택') {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = `<option value="">${placeholder}</option>`;
    items.forEach(it => {
        const o = document.createElement('option');
        o.value = it[val]; o.textContent = it[label];
        sel.appendChild(o);
    });
}

// ============================================================
// 네비게이션
// ============================================================

const PAGE_TITLES = {
    'dashboard':'대시보드','sales-reps':'영업 담당자 관리','companies':'업체 관리',
    'contacts':'업체 담당자 관리','meetings':'영업(미팅) 관리','codes':'코드 관리'
};

function navigate(sec) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.menu-item').forEach(m => m.classList.remove('active'));
    document.getElementById('section-'+sec)?.classList.add('active');
    document.querySelector(`[data-section="${sec}"]`)?.classList.add('active');
    document.getElementById('pageTitle').textContent = PAGE_TITLES[sec] || sec;
    ({
        'dashboard': () => Dashboard.render(),
        'sales-reps': () => SalesReps.render(),
        'companies': () => Companies.render(),
        'contacts': () => Contacts.render(),
        'meetings': () => Meetings.render(),
        'codes': () => Codes.render(),
    }[sec] || (() => {}))();
}

document.querySelectorAll('.menu-item').forEach(el =>
    el.addEventListener('click', () => navigate(el.dataset.section))
);

// ============================================================
// 인증
// ============================================================

async function doLogout() {
    await apiFetch('/api/logout', {method:'POST'});
    window.location.href = BASE + '/login';
}

function showChangePwModal() {
    ['currentPw','newPw','confirmPw'].forEach(id => document.getElementById(id).value = '');
    bootstrap.Modal.getOrCreateInstance(document.getElementById('changePwModal')).show();
}

async function doChangePassword() {
    const cur  = document.getElementById('currentPw').value;
    const nw   = document.getElementById('newPw').value;
    const conf = document.getElementById('confirmPw').value;
    if (!cur || !nw || !conf) { showToast('모든 항목을 입력하세요.','error'); return; }
    if (nw !== conf)           { showToast('새 비밀번호가 일치하지 않습니다.','error'); return; }
    const res = await apiFetch('/api/change-password',{method:'POST',body:JSON.stringify({current_password:cur,new_password:nw})});
    if (!res) return;
    const d = await res.json();
    if (d.success) {
        showToast('비밀번호가 변경되었습니다.');
        bootstrap.Modal.getInstance(document.getElementById('changePwModal'))?.hide();
    } else { showToast(d.message||'변경 실패','error'); }
}

// ============================================================
// 공유 캐시
// ============================================================

const Cache = {
    codes:{}, companies:[], salesReps:[],
    async loadCodes() {
        const r = await apiFetch('/api/codes'); if(!r) return;
        const all = await r.json();
        this.codes = {};
        all.forEach(c => { (this.codes[c.category] ??= []).push(c); });
    },
    async loadCompanies() { const r = await apiFetch('/api/companies'); if(r) this.companies = await r.json(); },
    async loadSalesReps() { const r = await apiFetch('/api/sales-reps'); if(r) this.salesReps = await r.json(); },
    async loadAll()       { await Promise.all([this.loadCodes(), this.loadCompanies(), this.loadSalesReps()]); }
};

function populateFromCodes(id, cat) {
    const codes = Cache.codes[cat] || [];
    populateSelect(id, codes, 'code_value', 'code_value');
}

// ============================================================
// 대시보드
// ============================================================

const Dashboard = {
    async render() {
        const r = await apiFetch('/api/dashboard'); if(!r) return;
        const d = await r.json();
        document.getElementById('dashboardContent').innerHTML = `
            <div class="dashboard-stats">
                <div class="stat-card"><div class="stat-icon blue"><i class="bi bi-building"></i></div><div class="stat-info"><div class="stat-num">${d.new_companies.length}</div><div class="stat-label">신규 등록 업체 (7일)</div></div></div>
                <div class="stat-card"><div class="stat-icon green"><i class="bi bi-person-lines-fill"></i></div><div class="stat-info"><div class="stat-num">${d.new_contacts.length}</div><div class="stat-label">신규 업체 담당자 (7일)</div></div></div>
                <div class="stat-card"><div class="stat-icon orange"><i class="bi bi-calendar-check-fill"></i></div><div class="stat-info"><div class="stat-num">${d.new_meetings.length}</div><div class="stat-label">신규 미팅 등록 (7일)</div></div></div>
            </div>
            ${this._section('bi-building','신규 등록 업체 (최근 7일)',
                d.new_companies.length === 0 ? null :
                d.new_companies.map(c=>`<tr><td style="width:45%"><strong>${c.company_name}</strong></td><td class="text-muted">${fmtDate(c.created_at)} 등록</td></tr>`).join('')
            )}
            ${this._section('bi-person-lines-fill','신규 등록 업체 담당자 (최근 7일)',
                d.new_contacts.length === 0 ? null :
                d.new_contacts.map(c=>`<tr><td style="width:25%"><strong>${c.name}</strong></td><td style="width:35%">${c.company_name}${c.department?' / '+c.department:''}</td><td class="text-muted">${fmtDate(c.created_at)} 등록</td></tr>`).join('')
            )}
            ${this._section('bi-calendar-check-fill','신규 등록 미팅 (최근 7일)',
                d.new_meetings.length === 0 ? null :
                d.new_meetings.map(m=>`<tr><td style="width:28%">${m.companies?m.companies.split(',').map(c=>`<span class="tag">${c.trim()}</span>`).join(' '):'-'}</td><td style="width:12%">${m.meeting_type?`<span class="tag">${m.meeting_type}</span>`:'-'}</td><td style="width:18%">${fmtDate(m.meeting_datetime)}</td><td>${(m.content||'').slice(0,60)}${m.content&&m.content.length>60?'...':''}</td></tr>`).join('')
            )}`;
    },
    _section(icon, title, rows) {
        return `<div class="dashboard-section">
            <div class="dashboard-section-header"><i class="bi ${icon}"></i>${title}</div>
            <table class="dashboard-table"><tbody>${rows||'<tr class="no-data-row"><td>데이터가 없습니다.</td></tr>'}</tbody></table>
        </div>`;
    }
};

// ============================================================
// 영업 담당자
// ============================================================

const SalesReps = {
    data:[],
    async render(search='') {
        const r = await apiFetch(`/api/sales-reps?search=${encodeURIComponent(search)}`); if(!r) return;
        this.data = await r.json(); this.renderTable();
    },
    renderTable() {
        const tbody = document.getElementById('srTableBody');
        const empty = document.getElementById('srEmpty');
        if (!this.data.length) { tbody.innerHTML=''; empty.classList.remove('d-none'); return; }
        empty.classList.add('d-none');
        tbody.innerHTML = this.data.map(r=>`<tr>
            <td>${fmt(r.emp_no)}</td><td><strong>${fmt(r.name)}</strong></td>
            <td>${fmt(r.rank)}</td><td>${fmt(r.position)}</td>
            <td>${fmt(r.phone)}</td><td>${fmt(r.email)}</td><td>${fmtDateOnly(r.created_at)}</td>
            <td><div class="action-btns">
                <button class="btn-edit" onclick="SalesReps.showEditModal(${r.id})">수정</button>
                <button class="btn-delete" onclick="SalesReps.delete(${r.id},'${escQ(r.name)}')">삭제</button>
            </div></td></tr>`).join('');
    },
    search(v) { clearTimeout(this._t); this._t = setTimeout(()=>this.render(v), 300); },
    async showAddModal() {
        await Cache.loadCodes();
        document.getElementById('srModalTitle').textContent='영업 담당자 추가';
        ['srId','srEmpNo','srName','srPhone','srEmail'].forEach(id=>document.getElementById(id).value='');
        populateFromCodes('srRank','직급'); populateFromCodes('srPosition','직책');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('srModal')).show();
    },
    async showEditModal(id) {
        await Cache.loadCodes();
        const r = await apiFetch(`/api/sales-reps/${id}`); if(!r) return;
        const d = await r.json();
        document.getElementById('srModalTitle').textContent='영업 담당자 수정';
        document.getElementById('srId').value      = d.id;
        document.getElementById('srEmpNo').value   = d.emp_no||'';
        document.getElementById('srName').value    = d.name||'';
        document.getElementById('srPhone').value   = d.phone||'';
        document.getElementById('srEmail').value   = d.email||'';
        populateFromCodes('srRank','직급'); populateFromCodes('srPosition','직책');
        document.getElementById('srRank').value     = d.rank||'';
        document.getElementById('srPosition').value = d.position||'';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('srModal')).show();
    },
    async save() {
        const id = document.getElementById('srId').value;
        const body = {
            emp_no:   document.getElementById('srEmpNo').value.trim(),
            name:     document.getElementById('srName').value.trim(),
            rank:     document.getElementById('srRank').value,
            position: document.getElementById('srPosition').value,
            phone:    document.getElementById('srPhone').value.trim(),
            email:    document.getElementById('srEmail').value.trim(),
        };
        if (!body.emp_no||!body.name) { showToast('사원번호와 성명은 필수입니다.','error'); return; }
        const r = await apiFetch(id?`/api/sales-reps/${id}`:'/api/sales-reps',{method:id?'PUT':'POST',body:JSON.stringify(body)});
        if (!r) return;
        const d = await r.json();
        if (d.success) {
            showToast(id?'수정되었습니다.':'등록되었습니다.');
            bootstrap.Modal.getInstance(document.getElementById('srModal'))?.hide();
            await this.render(document.getElementById('srSearch').value);
            await Cache.loadSalesReps();
        } else showToast(d.message||'저장 실패','error');
    },
    delete(id, name) {
        confirmDelete(`"${name}" 담당자를 삭제하시겠습니까?`, async () => {
            const r = await apiFetch(`/api/sales-reps/${id}`,{method:'DELETE'}); if(!r) return;
            const d = await r.json();
            if (d.success) { showToast('삭제되었습니다.'); await this.render(document.getElementById('srSearch').value); await Cache.loadSalesReps(); }
            else showToast('삭제 실패','error');
        });
    }
};

// ============================================================
// 업체
// ============================================================

const Companies = {
    data:[],
    async render(search='') {
        const r = await apiFetch(`/api/companies?search=${encodeURIComponent(search)}`); if(!r) return;
        this.data = await r.json(); this.renderTable();
    },
    renderTable() {
        const tbody = document.getElementById('compTableBody');
        const empty = document.getElementById('compEmpty');
        if (!this.data.length) { tbody.innerHTML=''; empty.classList.remove('d-none'); return; }
        empty.classList.add('d-none');
        tbody.innerHTML = this.data.map(c=>`<tr>
            <td><span class="text-muted small">${fmt(c.company_code)}</span></td>
            <td><strong>${fmt(c.company_name)}</strong></td><td>${fmt(c.ceo_name)}</td>
            <td>${fmt(c.business_reg_no)}</td><td>${fmt(c.corp_reg_no)}</td>
            <td style="max-width:160px">${c.solutions?.length
                ? c.solutions.slice(0,3).map(s=>`<span class="tag tag-solution">${s.code_value}</span>`).join('')
                  +(c.solutions.length>3?`<span class="tag tag-solution">+${c.solutions.length-3}</span>`:'')
                : '-'}</td>
            <td>${fmt(c.phone)}</td><td>${fmtDateOnly(c.created_at)}</td>
            <td><div class="action-btns">
                <button class="btn-edit" onclick="Companies.showEditModal(${c.id})">수정</button>
                <button class="btn-delete" onclick="Companies.delete(${c.id},'${escQ(c.company_name)}')">삭제</button>
            </div></td></tr>`).join('');
    },
    search(v) { clearTimeout(this._t); this._t = setTimeout(()=>this.render(v),300); },
    _renderSolutions(selIds=[]) {
        const sols = Cache.codes['솔루션']||[];
        document.getElementById('compSolutionList').innerHTML = sols.length === 0
            ? '<span class="text-muted small">등록된 솔루션이 없습니다.</span>'
            : sols.map(s=>`
                <label class="cb-item">
                    <input type="checkbox" value="${s.id}" ${selIds.includes(s.id)?'checked':''}>
                    <span>${s.code_value}</span>
                </label>`).join('');
    },
    async showAddModal() {
        await Cache.loadCodes();
        document.getElementById('compModalTitle').textContent='업체 추가';
        ['compId','compName','compCeo','compPhone','compBizNo','compCorpNo','compAddress'].forEach(id=>document.getElementById(id).value='');
        document.getElementById('compCode').value = '저장 시 자동생성';
        this._renderSolutions([]);
        bootstrap.Modal.getOrCreateInstance(document.getElementById('compModal')).show();
    },
    async showEditModal(id) {
        await Cache.loadCodes();
        const r = await apiFetch(`/api/companies/${id}`); if(!r) return;
        const c = await r.json();
        document.getElementById('compModalTitle').textContent='업체 수정';
        document.getElementById('compId').value      = c.id;
        document.getElementById('compCode').value    = c.company_code||'-';
        document.getElementById('compName').value    = c.company_name||'';
        document.getElementById('compCeo').value     = c.ceo_name||'';
        document.getElementById('compPhone').value   = c.phone||'';
        document.getElementById('compBizNo').value   = c.business_reg_no||'';
        document.getElementById('compCorpNo').value  = c.corp_reg_no||'';
        document.getElementById('compAddress').value = c.address||'';
        this._renderSolutions(c.solution_ids||[]);
        bootstrap.Modal.getOrCreateInstance(document.getElementById('compModal')).show();
    },
    _getSelSols() { return [...document.querySelectorAll('#compSolutionList input:checked')].map(cb=>parseInt(cb.value)); },
    async save() {
        const id = document.getElementById('compId').value;
        const body = {
            company_name:     document.getElementById('compName').value.trim(),
            ceo_name:         document.getElementById('compCeo').value.trim(),
            phone:            document.getElementById('compPhone').value.trim(),
            business_reg_no:  document.getElementById('compBizNo').value.trim(),
            corp_reg_no:      document.getElementById('compCorpNo').value.trim(),
            address:          document.getElementById('compAddress').value.trim(),
            solution_ids:     this._getSelSols(),
        };
        if (!body.company_name) { showToast('업체명은 필수입니다.','error'); return; }
        const r = await apiFetch(id?`/api/companies/${id}`:'/api/companies',{method:id?'PUT':'POST',body:JSON.stringify(body)});
        if (!r) return;
        const d = await r.json();
        if (d.success) {
            showToast(id?'수정되었습니다.':'등록되었습니다.');
            bootstrap.Modal.getInstance(document.getElementById('compModal'))?.hide();
            await this.render(document.getElementById('compSearch').value);
            await Cache.loadCompanies();
        } else showToast(d.message||'저장 실패','error');
    },
    delete(id, name) {
        confirmDelete(`"${name}" 업체를 삭제하시겠습니까?`, async () => {
            const r = await apiFetch(`/api/companies/${id}`,{method:'DELETE'}); if(!r) return;
            const d = await r.json();
            if (d.success) { showToast('삭제되었습니다.'); await this.render(document.getElementById('compSearch').value); await Cache.loadCompanies(); }
            else showToast('삭제 실패','error');
        });
    },
    showImportModal() {
        document.getElementById('importFile').value='';
        const res = document.getElementById('importResult');
        res.className='d-none'; res.innerHTML='';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('importModal')).show();
    },
    async doImport() {
        const file = document.getElementById('importFile').files[0];
        if (!file) { showToast('파일을 선택하세요.','error'); return; }
        const fd = new FormData(); fd.append('file', file);
        const r  = await fetch(BASE + '/api/companies/import',{method:'POST',body:fd});
        const d  = await r.json();
        const res = document.getElementById('importResult');
        res.className = '';
        if (d.success) {
            let html = `<div class="alert alert-success"><i class="bi bi-check-circle me-2"></i>${d.imported}건 등록 완료</div>`;
            if (d.errors?.length) html += `<div class="alert alert-warning"><strong>오류 행:</strong><ul class="mb-0 mt-1">${d.errors.map(e=>`<li>${e}</li>`).join('')}</ul></div>`;
            res.innerHTML = html;
            await this.render(document.getElementById('compSearch').value);
            await Cache.loadCompanies();
        } else {
            res.innerHTML = `<div class="alert alert-danger">${d.message}</div>`;
        }
    }
};

// ============================================================
// 업체 담당자
// ============================================================

const Contacts = {
    data:[],
    async render(search='') {
        const r = await apiFetch(`/api/contacts?search=${encodeURIComponent(search)}`); if(!r) return;
        this.data = await r.json(); this.renderTable();
    },
    renderTable() {
        const tbody = document.getElementById('ctTableBody');
        const empty = document.getElementById('ctEmpty');
        if (!this.data.length) { tbody.innerHTML=''; empty.classList.remove('d-none'); return; }
        empty.classList.add('d-none');
        const total = this.data.length;
        tbody.innerHTML = this.data.map((c,i)=>`<tr>
            <td class="text-center text-muted">${total - i}</td>
            <td><strong>${fmt(c.name)}</strong></td><td>${fmt(c.company_name)}</td>
            <td>${fmt(c.department)}</td><td>${fmt(c.rank)}</td><td>${fmt(c.position)}</td>
            <td>${fmt(c.job_type)}</td><td>${fmt(c.mobile_phone)}</td><td>${fmt(c.email)}</td>
            <td>${fmtDateOnly(c.created_at)}</td>
            <td><div class="action-btns">
                <button class="btn-view" onclick="Contacts.showDetail(${c.id})">상세</button>
                <button class="btn-edit" onclick="Contacts.showEditModal(${c.id})">수정</button>
                <button class="btn-delete" onclick="Contacts.delete(${c.id},'${escQ(c.name)}')">삭제</button>
            </div></td></tr>`).join('');
    },
    search(v) { clearTimeout(this._t); this._t = setTimeout(()=>this.render(v),300); },
    async _openModal(title, data=null) {
        await Cache.loadCodes(); await Cache.loadCompanies();
        document.getElementById('ctModalTitle').textContent = title;
        document.getElementById('ctId').value          = data?.id||'';
        document.getElementById('ctName').value        = data?.name||'';
        document.getElementById('ctDept').value        = data?.department||'';
        document.getElementById('ctOfficePhone').value = data?.office_phone||'';
        document.getElementById('ctMobilePhone').value = data?.mobile_phone||'';
        document.getElementById('ctEmail').value       = data?.email||'';
        // 이직 체크박스: 수정 시에만 표시, 초기화
        const transferRow = document.getElementById('ctTransferRow');
        const transferCb  = document.getElementById('ctIsTransfer');
        transferCb.checked = false;
        transferRow.classList.toggle('d-none', !data); // 추가 시 숨김, 수정 시 표시
        populateSelect('ctCompany', Cache.companies, 'id','company_name','업체 선택');
        populateFromCodes('ctRank','직급');
        populateFromCodes('ctPosition','직책');
        populateFromCodes('ctJobType','직군');
        if (data) {
            document.getElementById('ctCompany').value  = data.company_id||'';
            document.getElementById('ctRank').value     = data.rank||'';
            document.getElementById('ctPosition').value = data.position||'';
            document.getElementById('ctJobType').value  = data.job_type||'';
        }
        bootstrap.Modal.getOrCreateInstance(document.getElementById('ctModal')).show();
    },
    showAddModal() { this._openModal('업체 담당자 추가'); },
    async showEditModal(id) {
        const r = await apiFetch(`/api/contacts/${id}`); if(!r) return;
        this._openModal('업체 담당자 수정', await r.json());
    },
    async save() {
        const id = document.getElementById('ctId').value;
        const body = {
            name:         document.getElementById('ctName').value.trim(),
            company_id:   document.getElementById('ctCompany').value,
            department:   document.getElementById('ctDept').value.trim(),
            rank:         document.getElementById('ctRank').value,
            position:     document.getElementById('ctPosition').value,
            job_type:     document.getElementById('ctJobType').value,
            office_phone: document.getElementById('ctOfficePhone').value.trim(),
            mobile_phone: document.getElementById('ctMobilePhone').value.trim(),
            email:        document.getElementById('ctEmail').value.trim(),
            is_transfer:  id ? document.getElementById('ctIsTransfer').checked : false,
        };
        if (!body.name||!body.company_id) { showToast('성명과 업체명은 필수입니다.','error'); return; }
        const r = await apiFetch(id?`/api/contacts/${id}`:'/api/contacts',{method:id?'PUT':'POST',body:JSON.stringify(body)});
        if (!r) return;
        const d = await r.json();
        if (d.success) {
            showToast(id?'수정되었습니다.':'등록되었습니다.');
            bootstrap.Modal.getInstance(document.getElementById('ctModal'))?.hide();
            await this.render(document.getElementById('ctSearch').value);
        } else showToast(d.message||'저장 실패','error');
    },
    delete(id, name) {
        confirmDelete(`"${name}" 담당자를 삭제하시겠습니까?`, async () => {
            const r = await apiFetch(`/api/contacts/${id}`,{method:'DELETE'}); if(!r) return;
            const d = await r.json();
            if (d.success) { showToast('삭제되었습니다.'); await this.render(document.getElementById('ctSearch').value); }
            else showToast('삭제 실패','error');
        });
    },
    showImportModal() {
        document.getElementById('ctImportFile').value = '';
        const res = document.getElementById('ctImportResult');
        res.className = 'd-none'; res.innerHTML = '';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('ctImportModal')).show();
    },

    async doImport() {
        const file = document.getElementById('ctImportFile').files[0];
        if (!file) { showToast('파일을 선택하세요.', 'error'); return; }
        const fd = new FormData(); fd.append('file', file);
        const r  = await fetch(BASE + '/api/contacts/import', {method:'POST', body:fd});
        const d  = await r.json();
        const res = document.getElementById('ctImportResult');
        res.className = '';
        if (d.success) {
            let html = `<div class="alert alert-success"><i class="bi bi-check-circle me-2"></i>${d.imported}건 등록 완료</div>`;
            if (d.errors?.length) html += `<div class="alert alert-warning"><strong>오류 행:</strong><ul class="mb-0 mt-1">${d.errors.map(e=>`<li>${e}</li>`).join('')}</ul></div>`;
            res.innerHTML = html;
            await this.render(document.getElementById('ctSearch').value);
        } else {
            res.innerHTML = `<div class="alert alert-danger">${d.message}</div>`;
        }
    },

    async showDetail(id) {
        const r = await apiFetch(`/api/contacts/${id}`); if(!r) return;
        const c = await r.json();
        const hist  = c.meeting_history  || [];
        const hist2 = c.company_history  || [];

        // 회사 이력 섹션
        const compHistHtml = `
            <div class="detail-section-title mt-3"><i class="bi bi-building-check me-1"></i>회사 이력 (총 ${hist2.length + 1}곳)</div>
            <table class="data-table"><thead><tr><th>회사명</th><th>구분</th><th>퇴직일</th><th>등록일</th></tr></thead>
            <tbody>
                ${hist2.map(h=>`<tr>
                    <td>${h.company_name}</td>
                    <td><span class="tag">이전</span></td>
                    <td>${h.end_date||'-'}</td>
                    <td>${fmtDateOnly(h.created_at)}</td>
                </tr>`).join('')}
                <tr>
                    <td><strong>${fmt(c.company_name)}</strong></td>
                    <td><span class="tag tag-solution">현재</span></td>
                    <td>-</td>
                    <td>-</td>
                </tr>
            </tbody></table>`;

        document.getElementById('ctDetailBody').innerHTML = `
            <div class="contact-detail-grid mb-4">
                ${[['성명',c.name],['업체명',c.company_name],['부서명',c.department],['직급',c.rank],['직책',c.position],['직군',c.job_type],['일반전화',c.office_phone],['휴대폰',c.mobile_phone]].map(([l,v])=>`<div class="detail-item"><div class="detail-label">${l}</div><div class="detail-value">${fmt(v)}</div></div>`).join('')}
                <div class="detail-item" style="grid-column:1/-1"><div class="detail-label">이메일</div><div class="detail-value">${fmt(c.email)}</div></div>
            </div>
            ${compHistHtml}
            <div class="detail-section-title mt-3"><i class="bi bi-calendar-check me-1"></i>영업 이력 (${hist.length}건)</div>
            ${hist.length===0 ? '<div class="text-muted text-center py-3">영업 이력이 없습니다.</div>' :
            `<table class="data-table"><thead><tr><th>미팅구분</th><th>미팅일시</th><th>참석업체</th><th>영업담당자</th><th>미팅내용</th><th>결론</th></tr></thead>
            <tbody>${hist.map(m=>`<tr>
                <td>${m.meeting_type?`<span class="tag">${m.meeting_type}</span>`:'-'}</td>
                <td>${fmtDate(m.meeting_datetime)}</td>
                <td>${m.companies?m.companies.split(',').map(co=>`<span class="tag">${co.trim()}</span>`).join(' '):'-'}</td>
                <td>${fmt(m.sales_reps)}</td>
                <td style="max-width:180px;white-space:normal">${(m.content||'-').slice(0,80)}${m.content&&m.content.length>80?'...':''}</td>
                <td style="max-width:140px;white-space:normal">${(m.conclusion||'-').slice(0,60)}${m.conclusion&&m.conclusion.length>60?'...':''}</td>
            </tr>`).join('')}</tbody></table>`}`;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('ctDetailModal')).show();
    }
};

// ============================================================
// 영업(미팅) - 참석업체별 담당자 개별 선택 방식
// ============================================================

const Meetings = {
    data: [],
    _allContacts: [],
    // [{company_id, company_name, contact_id, contact_name}]
    _selectedParticipants: [],

    async render() { await this._load(); },

    async _load() {
        const sc = (document.getElementById('mtSearchCompany')?.value||'').trim();
        const ss = (document.getElementById('mtSearchContent')?.value||'').trim();
        const r  = await apiFetch(`/api/meetings?search_company=${encodeURIComponent(sc)}&search_content=${encodeURIComponent(ss)}`);
        if (!r) return;
        this.data = await r.json();
        this.renderTable();
    },

    renderTable() {
        const tbody = document.getElementById('mtTableBody');
        const empty = document.getElementById('mtEmpty');
        if (!this.data.length) { tbody.innerHTML=''; empty.classList.remove('d-none'); return; }
        empty.classList.add('d-none');
        tbody.innerHTML = this.data.map(m=>`<tr>
            <td style="max-width:160px;white-space:normal">${m.companies?m.companies.split(',').map(c=>`<span class="tag">${c.trim()}</span>`).join(' '):'-'}</td>
            <td>${m.meeting_type?`<span class="tag">${m.meeting_type}</span>`:'-'}</td>
            <td>${fmtDate(m.scheduled_datetime)}</td>
            <td>${fmtDate(m.meeting_datetime)}</td>
            <td style="max-width:180px">${(m.content||'').slice(0,50)}${m.content&&m.content.length>50?'...':''}</td>
            <td>${m.sales_reps?.map(r=>r.name).join(', ')||'-'}</td>
            <td>${fmt(m.registered_by_name)}</td>
            <td>${fmtDateOnly(m.created_at)}</td>
            <td><div class="action-btns">
                <button class="btn-view"   onclick="Meetings.showDetail(${m.id})">상세</button>
                <button class="btn-edit"   onclick="Meetings.showEditModal(${m.id})">수정</button>
                <button class="btn-delete" onclick="Meetings.delete(${m.id})">삭제</button>
            </div></td></tr>`).join('');
    },

    search() { clearTimeout(this._t); this._t = setTimeout(()=>this._load(),300); },

    // 업체 드롭다운 변경 시 담당자 옵션 표시
    onCompanySelect() {
        const cid  = parseInt(document.getElementById('mtSelectCompany').value||0);
        const area = document.getElementById('mtContactOptions');
        if (!cid) {
            area.innerHTML = '<span class="placeholder-text">업체를 선택하면 담당자 목록이 표시됩니다.</span>';
            return;
        }
        const contacts = this._allContacts.filter(c => c.company_id === cid);
        if (!contacts.length) {
            area.innerHTML = '<span class="placeholder-text">등록된 담당자가 없습니다.</span>';
            return;
        }
        area.innerHTML = contacts.map(c=>`
            <label class="cb-item">
                <input type="checkbox" class="mt-ct-cb" value="${c.id}" data-name="${c.name}">
                <span>${c.name}${c.department?' ('+c.department+')':''}</span>
            </label>`).join('');
    },

    // 선택된 담당자를 참석자 목록에 추가
    addParticipants() {
        const cid    = parseInt(document.getElementById('mtSelectCompany').value||0);
        const comp   = Cache.companies.find(c=>c.id===cid);
        if (!comp) { showToast('업체를 선택하세요.','error'); return; }

        const checked = [...document.querySelectorAll('.mt-ct-cb:checked')];
        if (!checked.length) { showToast('담당자를 선택하세요.','error'); return; }

        checked.forEach(cb => {
            const contactId = parseInt(cb.value);
            if (!this._selectedParticipants.some(p=>p.contact_id===contactId)) {
                this._selectedParticipants.push({
                    company_id:   cid,
                    company_name: comp.company_name,
                    contact_id:   contactId,
                    contact_name: cb.dataset.name,
                });
            }
        });

        // 체크 해제 후 렌더
        checked.forEach(cb=>cb.checked=false);
        this._renderParticipants();
    },

    removeParticipant(contactId) {
        this._selectedParticipants = this._selectedParticipants.filter(p=>p.contact_id!==contactId);
        this._renderParticipants();
    },

    _renderParticipants() {
        const box = document.getElementById('mtSelectedParticipants');
        if (!this._selectedParticipants.length) {
            box.innerHTML = '<span class="placeholder-text">아직 선택된 참석자가 없습니다.</span>';
            return;
        }
        // 업체별 그룹
        const grouped = {};
        this._selectedParticipants.forEach(p => {
            (grouped[p.company_id] ??= {name:p.company_name, contacts:[]}).contacts.push(p);
        });
        box.innerHTML = Object.values(grouped).map(g=>`
            <div class="participant-group">
                <div class="participant-company-label"><i class="bi bi-building me-1"></i>${g.name}</div>
                <div class="participant-tags">
                    ${g.contacts.map(p=>`
                        <span class="participant-tag">
                            ${p.contact_name}
                            <button type="button" class="btn-remove-pt" onclick="Meetings.removeParticipant(${p.contact_id})" title="제거">
                                <i class="bi bi-x"></i>
                            </button>
                        </span>`).join('')}
                </div>
            </div>`).join('');
    },

    async _prepareModal() {
        await Cache.loadCompanies();
        await Cache.loadSalesReps();

        // 모든 담당자 로드
        const r = await apiFetch('/api/contacts'); if(!r) return;
        this._allContacts = await r.json();

        // 업체 드롭다운
        populateSelect('mtSelectCompany', Cache.companies,'id','company_name','업체를 선택하세요');

        // 담당자 옵션 초기화
        document.getElementById('mtContactOptions').innerHTML =
            '<span class="placeholder-text">업체를 선택하면 담당자 목록이 표시됩니다.</span>';

        // 영업담당자 체크박스
        const repBox = document.getElementById('mtSalesRepList');
        repBox.innerHTML = Cache.salesReps.length === 0
            ? '<span class="text-muted small">등록된 영업 담당자가 없습니다.</span>'
            : Cache.salesReps.map(r=>`
                <label class="cb-item">
                    <input type="checkbox" class="mt-rep-cb" value="${r.id}">
                    <span>${r.name}${r.rank?' ('+r.rank+')':''}</span>
                </label>`).join('');

        // 등록자
        populateSelect('mtRegisteredBy', Cache.salesReps,'id','name','선택');
    },

    async showAddModal() {
        document.getElementById('mtModalTitle').textContent='미팅 추가';
        ['mtId','mtType','mtScheduled','mtDatetime','mtContent','mtConclusion','mtFollowUp'].forEach(id=>{
            const el=document.getElementById(id); if(el) el.value='';
        });
        this._selectedParticipants = [];
        await this._prepareModal();
        this._renderParticipants();
        bootstrap.Modal.getOrCreateInstance(document.getElementById('mtModal')).show();
    },

    async showEditModal(id) {
        const r = await apiFetch(`/api/meetings/${id}`); if(!r) return;
        const m = await r.json();

        document.getElementById('mtModalTitle').textContent='미팅 수정';
        document.getElementById('mtId').value        = m.id;
        document.getElementById('mtType').value      = m.meeting_type||'';
        document.getElementById('mtScheduled').value = m.scheduled_datetime?m.scheduled_datetime.slice(0,16):'';
        document.getElementById('mtDatetime').value  = m.meeting_datetime?m.meeting_datetime.slice(0,16):'';
        document.getElementById('mtContent').value   = m.content||'';
        document.getElementById('mtConclusion').value= m.conclusion||'';
        document.getElementById('mtFollowUp').value  = m.follow_up||'';

        // 기존 참석자 복원
        this._selectedParticipants = (m.contacts||[]).map(c=>({
            company_id:   c.company_id,
            company_name: c.company_name,
            contact_id:   c.id,
            contact_name: c.name,
        }));

        await this._prepareModal();
        this._renderParticipants();

        // 영업담당자 복원
        (m.sales_rep_ids||[]).forEach(rid=>{
            const cb = document.querySelector(`.mt-rep-cb[value="${rid}"]`);
            if (cb) cb.checked = true;
        });

        document.getElementById('mtRegisteredBy').value = m.registered_by||'';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('mtModal')).show();
    },

    async save() {
        const id          = document.getElementById('mtId').value;
        const company_ids = [...new Set(this._selectedParticipants.map(p=>p.company_id))];
        const contact_ids = this._selectedParticipants.map(p=>p.contact_id);
        const sales_rep_ids = [...document.querySelectorAll('.mt-rep-cb:checked')].map(cb=>parseInt(cb.value));

        const body = {
            meeting_type:       document.getElementById('mtType').value,
            scheduled_datetime: document.getElementById('mtScheduled').value||null,
            meeting_datetime:   document.getElementById('mtDatetime').value||null,
            content:            document.getElementById('mtContent').value.trim(),
            conclusion:         document.getElementById('mtConclusion').value.trim(),
            follow_up:          document.getElementById('mtFollowUp').value.trim(),
            registered_by:      document.getElementById('mtRegisteredBy').value||null,
            company_ids, contact_ids, sales_rep_ids,
        };

        const r = await apiFetch(id?`/api/meetings/${id}`:'/api/meetings',{method:id?'PUT':'POST',body:JSON.stringify(body)});
        if (!r) return;
        const d = await r.json();
        if (d.success) {
            showToast(id?'수정되었습니다.':'등록되었습니다.');
            bootstrap.Modal.getInstance(document.getElementById('mtModal'))?.hide();
            await this._load();
        } else showToast(d.message||'저장 실패','error');
    },

    delete(id) {
        confirmDelete('이 미팅을 삭제하시겠습니까?', async () => {
            const r = await apiFetch(`/api/meetings/${id}`,{method:'DELETE'}); if(!r) return;
            const d = await r.json();
            if (d.success) { showToast('삭제되었습니다.'); await this._load(); }
            else showToast('삭제 실패','error');
        });
    },

    async showDetail(id) {
        const r = await apiFetch(`/api/meetings/${id}`); if(!r) return;
        const m = await r.json();

        // 참석자를 업체별로 그룹화
        const grouped = {};
        (m.contacts||[]).forEach(c => {
            (grouped[c.company_id] ??= {name:c.company_name, contacts:[]}).contacts.push(c.name);
        });
        const participantHtml = Object.values(grouped).length === 0 ? '-' :
            Object.values(grouped).map(g=>`
                <div class="mb-1"><span class="fw-semibold">${g.name}:</span>
                ${g.contacts.map(n=>`<span class="tag ms-1">${n}</span>`).join('')}</div>
            `).join('');

        document.getElementById('mtDetailBody').innerHTML = `
            <div class="row g-3">
                <div class="col-md-6">
                    <div class="detail-section-title">기본 정보</div>
                    ${[['미팅구분', m.meeting_type?`<span class="tag">${m.meeting_type}</span>`:'-'],
                       ['미팅예정일시', fmtDate(m.scheduled_datetime)],
                       ['미팅일시',     fmtDate(m.meeting_datetime)],
                       ['등록자',       fmt(m.registered_by_name)]
                    ].map(([l,v])=>`<div class="detail-item mb-2"><div class="detail-label">${l}</div><div class="detail-value">${v}</div></div>`).join('')}
                </div>
                <div class="col-md-6">
                    <div class="detail-section-title">참석업체/담당자</div>
                    <div class="mb-3">${participantHtml}</div>
                    <div class="detail-section-title">영업 담당자</div>
                    <div>${m.sales_reps?.length?m.sales_reps.map(r=>`<span class="tag">${r.name}</span>`).join(' '):'-'}</div>
                </div>
                <div class="col-12 meeting-detail-section"><div class="detail-section-title">미팅내용</div><div style="white-space:pre-wrap;font-size:.875rem">${m.content||'-'}</div></div>
                <div class="col-md-6 meeting-detail-section"><div class="detail-section-title">결론</div><div style="white-space:pre-wrap;font-size:.875rem">${m.conclusion||'-'}</div></div>
                <div class="col-md-6 meeting-detail-section"><div class="detail-section-title">후속과제</div><div style="white-space:pre-wrap;font-size:.875rem">${m.follow_up||'-'}</div></div>
            </div>`;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('mtDetailModal')).show();
    }
};

// ============================================================
// 코드 관리
// ============================================================

const Codes = {
    currentCat: '직급', data:[],
    async render() { await this.loadCat(this.currentCat); },
    async loadCat(cat) {
        this.currentCat = cat;
        document.getElementById('codeCurrentCat').textContent = cat;
        document.getElementById('codeAddBtnText').textContent = cat;
        const r = await apiFetch(`/api/codes?category=${encodeURIComponent(cat)}`); if(!r) return;
        this.data = await r.json(); this.renderTable();
    },
    renderTable() {
        const tbody = document.getElementById('codeTableBody');
        const empty = document.getElementById('codeEmpty');
        if (!this.data.length) { tbody.innerHTML=''; empty.classList.remove('d-none'); return; }
        empty.classList.add('d-none');
        tbody.innerHTML = this.data.map((c,i)=>`<tr>
            <td>${i+1}</td><td><strong>${fmt(c.code_value)}</strong></td><td>${fmtDateOnly(c.created_at)}</td>
            <td><div class="action-btns">
                <button class="btn-edit"   onclick="Codes.showEditModal(${c.id},'${escQ(c.code_value)}')">수정</button>
                <button class="btn-delete" onclick="Codes.delete(${c.id},'${escQ(c.code_value)}')">삭제</button>
            </div></td></tr>`).join('');
    },
    switchTab(cat, btn) {
        document.querySelectorAll('.code-tab').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        this.loadCat(cat);
    },
    showAddModal() {
        document.getElementById('codeModalTitle').textContent=`${this.currentCat} 추가`;
        document.getElementById('codeId').value=''; document.getElementById('codeValue').value='';
        bootstrap.Modal.getOrCreateInstance(document.getElementById('codeModal')).show();
    },
    showEditModal(id, val) {
        document.getElementById('codeModalTitle').textContent=`${this.currentCat} 수정`;
        document.getElementById('codeId').value=id; document.getElementById('codeValue').value=val;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('codeModal')).show();
    },
    async save() {
        const id  = document.getElementById('codeId').value;
        const val = document.getElementById('codeValue').value.trim();
        if (!val) { showToast('코드값을 입력하세요.','error'); return; }
        const body = id ? {code_value:val} : {category:this.currentCat, code_value:val};
        const r = await apiFetch(id?`/api/codes/${id}`:'/api/codes',{method:id?'PUT':'POST',body:JSON.stringify(body)});
        if (!r) return;
        const d = await r.json();
        if (d.success) {
            showToast(id?'수정되었습니다.':'등록되었습니다.');
            bootstrap.Modal.getInstance(document.getElementById('codeModal'))?.hide();
            await this.loadCat(this.currentCat);
            await Cache.loadCodes();
        } else showToast(d.message||'저장 실패','error');
    },
    delete(id, val) {
        confirmDelete(`"${val}"을(를) 삭제하시겠습니까?`, async () => {
            const r = await apiFetch(`/api/codes/${id}`,{method:'DELETE'}); if(!r) return;
            const d = await r.json();
            if (d.success) { showToast('삭제되었습니다.'); await this.loadCat(this.currentCat); await Cache.loadCodes(); }
            else showToast('삭제 실패','error');
        });
    }
};

// ============================================================
// 초기화
// ============================================================

function escQ(s) { return String(s||'').replace(/'/g,"\\'"); }

async function init() {
    const r = await apiFetch('/api/session'); if(!r) return;
    const s = await r.json();
    if (s.logged_in) {
        document.getElementById('sidebarUsername').textContent = s.username;
        document.getElementById('topUsername').textContent     = s.username;
    }
    await Cache.loadAll();
    navigate('dashboard');
}

init();
