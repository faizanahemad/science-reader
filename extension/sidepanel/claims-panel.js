/**
 * ClaimsPanel — Read-only overlay panel for browsing PKB claims/memories.
 *
 * Search (debounced 300ms), filter by type/domain/status, paginated via "Load more".
 * Uses GET /pkb/claims endpoint via API.getClaims().
 *
 * Depends on: API (from shared/api.js) available as global via sidepanel.js import.
 */

var ClaimsPanel = (function() {
    var _claims = [];
    var _offset = 0;
    var _limit = 20;
    var _total = 0;
    var _searchDebounce = null;

    function init() {
        var searchInput = document.getElementById('claims-search');
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                clearTimeout(_searchDebounce);
                _searchDebounce = setTimeout(function() { _resetAndLoad(); }, 300);
            });
        }
        ['claims-filter-type', 'claims-filter-domain', 'claims-filter-status'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.addEventListener('change', function() { _resetAndLoad(); });
        });
        var loadMoreBtn = document.getElementById('claims-load-more-btn');
        if (loadMoreBtn) {
            loadMoreBtn.addEventListener('click', function() { _loadMore(); });
        }
    }

    function _getFilters() {
        var params = { limit: _limit, offset: _offset };
        var query = (document.getElementById('claims-search') || {}).value || '';
        var claimType = (document.getElementById('claims-filter-type') || {}).value || '';
        var domain = (document.getElementById('claims-filter-domain') || {}).value || '';
        var status = (document.getElementById('claims-filter-status') || {}).value || '';
        if (query.trim()) params.query = query.trim();
        if (claimType) params.claim_type = claimType;
        if (domain) params.context_domain = domain;
        if (status) params.status = status;
        return params;
    }

    function _resetAndLoad() {
        _offset = 0;
        _claims = [];
        loadClaims();
    }

    async function loadClaims() {
        try {
            var params = _getFilters();
            var result = await API.getClaims(params);
            var newClaims = result.claims || [];
            _total = result.count || 0;

            if (_offset === 0) {
                _claims = newClaims;
            } else {
                _claims = _claims.concat(newClaims);
            }
            _renderClaims();
        } catch (err) {
            console.error('[ClaimsPanel] Failed to load claims:', err);
        }
    }

    function _loadMore() {
        _offset += _limit;
        loadClaims();
    }

    function _renderClaims() {
        var container = document.getElementById('claims-list');
        var loadMoreEl = document.getElementById('claims-load-more');
        if (!container) return;

        if (_claims.length === 0) {
            container.innerHTML = '<div class="claims-empty">No claims found</div>';
            if (loadMoreEl) loadMoreEl.classList.add('hidden');
            return;
        }

        container.innerHTML = _claims.map(function(claim) {
            var typeBadge = '<span class="claim-badge claim-type-' + claim.claim_type + '">'
                + claim.claim_type + '</span>';
            var domainBadge = claim.context_domain
                ? '<span class="claim-badge claim-domain">' + claim.context_domain + '</span>' : '';
            var statusBadge = claim.status !== 'active'
                ? '<span class="claim-badge claim-status-' + claim.status + '">' + claim.status + '</span>' : '';
            var refId = claim.friendly_id
                ? '<span class="claim-ref">@' + claim.friendly_id + '</span>' : '';
            var claimNum = claim.claim_number
                ? '<span class="claim-num">#' + claim.claim_number + '</span>' : '';

            return '<div class="claim-card">' +
                '<div class="claim-statement">' + _escapeHtml(claim.statement) + '</div>' +
                '<div class="claim-meta">' +
                    claimNum + refId + typeBadge + domainBadge + statusBadge +
                '</div>' +
            '</div>';
        }).join('');

        if (loadMoreEl) {
            loadMoreEl.classList.toggle('hidden', _claims.length >= _total);
        }
    }

    function _escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    function show() {
        document.getElementById('claims-panel').classList.remove('hidden');
        if (_claims.length === 0) { _resetAndLoad(); }
    }

    function hide() {
        document.getElementById('claims-panel').classList.add('hidden');
    }

    function toggle() {
        var panel = document.getElementById('claims-panel');
        if (panel.classList.contains('hidden')) { show(); } else { hide(); }
    }

    return {
        init: init, show: show, hide: hide, toggle: toggle, loadClaims: loadClaims
    };
})();
