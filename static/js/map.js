// 강남역 중심 좌표
const GANGNAM_STATION = { lat: 37.4979, lng: 127.0276 };

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

kakao.maps.load(async () => {
  const map = new kakao.maps.Map(document.getElementById("map"), {
    center: new kakao.maps.LatLng(GANGNAM_STATION.lat, GANGNAM_STATION.lng),
    level: 4,
  });

  const places = await fetch("/api/places").then((r) => r.json());
  let openInfo = null;

  places.forEach((p) => {
    const position = new kakao.maps.LatLng(p.lat, p.lng);
    const marker = new kakao.maps.Marker({ map, position });
    const info = new kakao.maps.InfoWindow({
      content: `
        <div style="padding:8px;font-size:12px;line-height:1.5;min-width:180px;">
          <strong>${escapeHtml(p.name)}</strong><br>
          ${escapeHtml(p.address)}<br>
          24시간: ${escapeHtml(p.is_24h)} · 반려동물: ${escapeHtml(p.pet_friendly)}<br>
          <a href="${encodeURI(p.kakao_url)}" target="_blank" rel="noopener">카카오맵에서 보기</a>
        </div>`,
      removable: true,
    });
    kakao.maps.event.addListener(marker, "click", () => {
      if (openInfo) openInfo.close();
      info.open(map, marker);
      openInfo = info;
    });
  });
});
