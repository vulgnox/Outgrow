'use strict';
/* RAGDAMAXING social profiles: avatars, banners and custom status.
   Lives in app.js's modal() and reuses its globals (S, api, esc, avatar, modal, toast, render). */

const Profiles = {};
const PD = { uid: 0, data: null };

async function profLoad(uid) {
  const P = await api('profile?uid=' + uid);
  PD.uid = uid;
  PD.data = P;
  return P;
}

Profiles.edit = async function (uid) {
  uid = uid || (S.user && S.user.id);
  if (!uid) return;
  try {
    const P = await profLoad(uid);
    if (!P.user.me) return;
  } catch (e) { return; }
  Profiles.paint();
};

Profiles.paint = function () {
  const P = PD.data;
  if (!P) return;
  const u = P.user, soc = P.social || {}, st = soc.status || {};
  const statusLine = [st.emoji || '', st.text || ''].join(' ').trim();
  const photo = soc.banner && !soc.banner_style;
  PD.bannerStyle = soc.banner_style || (soc.banner ? 'photo' : '');
  const bannerCls = photo ? '' : (soc.banner_style ? ' b-' + soc.banner_style : ' ph');
  const bannerOpt = (v, label) => { const on = PD.bannerStyle === v || (v === 'none' && !PD.bannerStyle); return `<button type="button" class="prof-banner-opt ${on ? 'on' : ''}" data-pact="bannerStyle" data-v="${v}" aria-pressed="${on}" title="${label}"><span class="b-${v}"></span><b>${label}</b></button>`; };
  modal(`<div class="mg prof-edit">
    <div class="row between mg-top"><div><div class="xs mut up">Your profile</div><h2>Edit profile</h2></div>
      <button class="btn-s ico" data-pact="close" aria-label="Close">${ic('x', 14)}</button></div>
    <div class="prof-banner edit${bannerCls}"${photo ? ` style="background-image:url('${esc(soc.banner)}')"` : ''}>
      ${photo ? '' : `<span class="xs mut">${soc.banner_style && soc.banner_style !== 'none' ? 'Gradient banner' : 'No banner'}</span>`}
      <div class="prof-banner-acts">
        <button class="btn-s" data-pact="pickBanner">Upload</button>
        ${soc.banner ? '<button class="btn-s" data-pact="clearBanner">Remove photo</button>' : ''}
      </div>
    </div>
    <div class="prof-banners">
      ${soc.banner ? bannerOpt('photo', 'Photo') : ''}
      ${['aurora', 'sunset', 'mint', 'mono', 'blossom'].map(k => bannerOpt(k, k[0].toUpperCase() + k.slice(1))).join('')}
      ${bannerOpt('none', 'None')}
    </div>
    <div class="prof-top">
      ${avatar(u.emoji, u.color, 'lg', null, { pimg: soc.avatar })}
      <div class="grow">
        <b>${esc(u.display)}</b><div class="xs mut">@${esc(u.username || u.display)}</div>
        <div class="prof-status">${statusLine ? esc(statusLine) : '<span class="mut">No status yet</span>'}</div>
      </div>
      <div class="col g4">
        <button class="btn-s" data-pact="pickAvatar">Avatar</button>
        ${soc.avatar ? '<button class="btn-s" data-pact="clearAvatar">Remove</button>' : ''}
      </div>
    </div>
    <div class="grid2 mt12">
      <div><label>Display name</label><input id="prof_name" maxlength="20" value="${esc(u.display)}" placeholder="Your name"></div>
      <div><label>Pronouns</label><input id="prof_pronouns" maxlength="24" value="${esc(soc.pronouns || '')}" placeholder="he / him"></div>
    </div>
    <label>Bio</label><textarea id="prof_bio" maxlength="160" rows="3" placeholder="What you're working toward, in your own words.">${esc(soc.bio || '')}</textarea>
    <div class="grid2">
      <div><label>Identity</label><input id="prof_identity" maxlength="140" value="${esc(u.identity || '')}" placeholder="I am becoming someone who…"></div>
      <div><label>Profile colour</label><input id="prof_color" type="color" value="${esc(u.color || '#7c6af7')}" style="width:100%;height:38px;padding:3px"></div>
    </div>
    <div class="lbl2 mt12">Custom status</div>
    <div class="row g8">
      <input id="prof_status_emoji" class="prof-emoji" maxlength="16" placeholder="📚" value="${esc(st.emoji || '')}" aria-label="Status emoji">
      <input id="prof_status_text" class="grow" maxlength="80" placeholder="Deep in integrals" value="${esc(st.text || '')}" aria-label="Status text">
    </div>
    <div class="row g8 mt8">
      <button class="btn-p grow" data-pact="saveProfile">Save profile</button>
      <button class="btn-s" data-pact="saveStatus">Save status only</button>
      <button class="btn-s" data-pact="clearStatus">Clear</button>
    </div>
    <p class="xs mut mt8">Avatar max 2 MB / 1024px · banner max 4 MB / 4096px · PNG, JPEG, GIF or WebP. Only people who share a crew or server with you, or are your friend, can see them.</p>
    <input type="file" id="prof_avatar_file" accept="image/png,image/jpeg,image/gif,image/webp" hidden>
    <input type="file" id="prof_banner_file" accept="image/png,image/jpeg,image/gif,image/webp" hidden>
  </div>`, true);
};

Profiles.refresh = async function () {
  try {
    await profLoad(PD.uid);
  } catch (e) { return; }
  Profiles.paint();
  try { const me = await api('me'); S.user = me.user; } catch (e) { }
  if (window.Chat) { try { await Chat.load(); } catch (e) { } }
  render();
};

async function profUpload(kind, file) {
  if (!file) return;
  const cap = kind === 'avatar' ? 2 * 1024 * 1024 : 4 * 1024 * 1024;
  try {
    const send = await shrinkImage(file, kind === 'avatar' ? 512 : 1600, 0.9);
    if (send.size > cap) { toast('Too big', `${kind === 'avatar' ? 'Avatar' : 'Banner'} is over ${cap / 1048576} MB`); return; }
    const res = await fetch('/api/profile/upload?kind=' + kind, {
      method: 'POST', body: send, credentials: 'same-origin',
      headers: { 'X-File-Name': encodeURIComponent(send.name || file.name), 'X-File-Type': send.type || 'image/png' },
    });
    const r = await res.json().catch(() => ({}));
    if (!res.ok) { toast('Upload failed', r.error || ('HTTP ' + res.status)); return; }
    toast(kind === 'avatar' ? 'Avatar updated' : 'Banner updated');
    await Profiles.refresh();
  } catch (e) { toast('Upload failed', 'Check your connection'); }
}

async function profClear(kind) {
  try {
    await api('profile/clear', { kind });
    toast(kind === 'avatar' ? 'Avatar removed' : 'Banner removed');
    await Profiles.refresh();
  } catch (e) { }
}

const PA = {
  close: () => closeModal(),
  editProfile: el => Profiles.edit(+el.dataset.uid || (S.user && S.user.id)),
  pickAvatar: () => document.getElementById('prof_avatar_file')?.click(),
  pickBanner: () => document.getElementById('prof_banner_file')?.click(),
  clearAvatar: async () => { if (await confirmSheet('Remove your profile picture?', 'Remove', true)) await profClear('avatar'); },
  clearBanner: async () => { if (await confirmSheet('Remove your banner?', 'Remove', true)) await profClear('banner'); },
  bannerStyle: el => {
    const v = el.dataset.v || '';
    PD.bannerStyle = v;
    document.querySelectorAll('[data-pact="bannerStyle"]').forEach(b => {
      const on = (b.dataset.v || '') === v;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
    });
    const banner = document.querySelector('.prof-banner.edit');
    if (!banner) return;
    const soc = (PD.data && PD.data.social) || {};
    banner.className = 'prof-banner edit';
    banner.style.backgroundImage = '';
    if (v === 'photo' && soc.banner) banner.style.backgroundImage = `url("${soc.banner}")`;
    else if (v) banner.classList.add('b-' + v);
    else banner.classList.add('ph');
    const lbl = banner.querySelector('.xs');
    if (lbl) {
      lbl.style.display = v === 'photo' ? 'none' : '';
      if (v !== 'photo') lbl.textContent = v && v !== 'none' ? 'Gradient banner' : 'No banner';
    }
  },
  saveProfile: async () => {
    const val = id => (document.getElementById(id) || {}).value || '';
    if (!val('prof_name').trim()) { toast('Profile', 'Display name cannot be empty'); return; }
    const style = PD.bannerStyle === 'photo' ? '' : (PD.bannerStyle || '');
    try {
      await api('settings', { display: val('prof_name'), identity: val('prof_identity'), color: val('prof_color') });
      await api('profile/details', { bio: val('prof_bio'), pronouns: val('prof_pronouns'), banner_style: style });
      toast('Profile saved', 'Your card is up to date');
      await Profiles.refresh();
    } catch (e) { }
  },
  saveStatus: async () => {
    const emoji = (document.getElementById('prof_status_emoji') || {}).value || '';
    const text = (document.getElementById('prof_status_text') || {}).value || '';
    try { await api('profile/status', { text, emoji }); toast('Status saved'); await Profiles.refresh(); } catch (e) { }
  },
  clearStatus: async () => {
    try { await api('profile/status', { text: '', emoji: '' }); toast('Status cleared'); await Profiles.refresh(); } catch (e) { }
  },
  message: async el => {
    const uid = +el.dataset.uid;
    closeModal();
    if (S.tab !== 'chat') await go('chat');
    if (window.Chat) Chat.openDM(uid);
  },
};

document.addEventListener('click', e => {
  const el = e.target.closest('[data-pact]');
  if (!el) return;
  e.preventDefault(); e.stopPropagation();
  const fn = PA[el.dataset.pact];
  if (fn) { try { fn(el); } catch (x) { console.error(x); } }
});

document.addEventListener('change', e => {
  if (e.target.id === 'prof_avatar_file') { profUpload('avatar', e.target.files[0]); e.target.value = ''; }
  if (e.target.id === 'prof_banner_file') { profUpload('banner', e.target.files[0]); e.target.value = ''; }
});

window.Profiles = Profiles;
