(function() {
    "use strict";

    const select = (el, all = false) => {
      el = el.trim()
      if (all) {
        return [...document.querySelectorAll(el)]
      } else {
        return document.querySelector(el)
      }
    }

    const on = (type, el, listener, all = false) => {
      let selectEl = select(el, all)
      if (selectEl) {
        if (all) {
          selectEl.forEach(e => e.addEventListener(type, listener))
        } else {
          selectEl.addEventListener(type, listener)
        }
      }
    }

    document.addEventListener('DOMContentLoaded', function() {
        const copyright = document.getElementById("copyright");
        var date = new Date();
        var year = date.getFullYear();
        copyright.innerHTML = `<p>© ${year} NEBULA. All rights reserved.<br><a href="https://docs.nebula-dfl.com/" target="_blank"><i class="fa fa-book"></i> Documentation</a> | <a href="https://github.com/CyberDataLab/nebula" target="_blank"><i class="fa fa-code"></i>  Source code</a></p>`;
    });

    on('click', '.mobile-nav-toggle', function(e) {
      select('#navbar').classList.toggle('navbar-mobile')
      this.classList.toggle('bi-list')
      this.classList.toggle('bi-x')
    })

    on('click', '.navbar .dropdown > a', function(e) {
      if (select('#navbar').classList.contains('navbar-mobile')) {
        e.preventDefault()
        this.nextElementSibling.classList.toggle('dropdown-active')
      }
    }, true)

    let preloader = select('#preloader');
    if (preloader) {
      window.addEventListener('load', () => {
        preloader.remove()
      });
    }

  })()
