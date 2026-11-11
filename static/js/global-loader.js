(function () {
  const DEBUG = true; // set to false once confirmed working

  const loader = document.getElementById('globalLoader');
  if (!loader) {
    console.error('[loader] #globalLoader element not found in DOM — check base.html markup');
    return;
  }
  const bar = loader.querySelector('.global-loader-bar');
  let activeRequests = 0;

  function showLoader(source) {
    activeRequests++;
    if (DEBUG) console.log('[loader] show ->', source, 'active:', activeRequests);
    loader.classList.remove('done');
    loader.classList.add('active');
  }

  function hideLoader(source) {
    activeRequests = Math.max(0, activeRequests - 1);
    if (DEBUG) console.log('[loader] hide ->', source, 'active:', activeRequests);
    if (activeRequests === 0) {
    //   loader.classList.add('done');
    //   setTimeout(() => {
    //     loader.classList.remove('active', 'done');
    //     bar.style.width = '0%';
    //   }, 250);
    }
  }

  // ---- Patch fetch() ----
  if (window.fetch) {
    const originalFetch = window.fetch;
    window.fetch = function (...args) {
      showLoader('fetch: ' + (args[0] && args[0].url ? args[0].url : args[0]));
      return originalFetch.apply(this, args)
        .then((res) => { hideLoader('fetch'); return res; })
        .catch((err) => { hideLoader('fetch (error)'); throw err; });
    };
    if (DEBUG) console.log('[loader] fetch patched');
  }

  // ---- Patch XMLHttpRequest (covers jQuery $.ajax too) ----
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this._trackedByLoader = true;
    this._loaderUrl = url;
    return originalOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    if (this._trackedByLoader) {
      showLoader('xhr: ' + this._loaderUrl);
      this.addEventListener('loadend', () => hideLoader('xhr: ' + this._loaderUrl));
    }
    return originalSend.apply(this, args);
  };
  if (DEBUG) console.log('[loader] XHR patched');

  // ---- Plain <form> submissions ----
  document.addEventListener('submit', function (e) {
    const form = e.target;
    if (form.tagName === 'FORM' && !form.hasAttribute('data-no-loader')) {
      showLoader('form submit: ' + (form.action || location.href));
    }
  }, true);

  window.addEventListener('pageshow', () => {
    activeRequests = 0;
    loader.classList.remove('active', 'done');
    bar.style.width = '0%';
  });

  if (DEBUG) console.log('[loader] global-loader.js fully initialized');

  // ---- One-time diagnostic: report computed position/z-index/visibility ----
  if (DEBUG) {
    const rect = loader.getBoundingClientRect();
    const cs = getComputedStyle(loader);
    console.log('[loader] #globalLoader computed style ->', {
      position: cs.position,
      top: cs.top,
      zIndex: cs.zIndex,
      display: cs.display,
      opacity: cs.opacity,
      width: cs.width,
      height: cs.height,
      boundingRect: rect
    });
  }
})();