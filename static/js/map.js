// 강남역 중심 좌표
const GANGNAM_STATION = { lat: 37.4979, lng: 127.0276 };

kakao.maps.load(async () => {
  const map = new kakao.maps.Map(document.getElementById("map"), {
    center: new kakao.maps.LatLng(GANGNAM_STATION.lat, GANGNAM_STATION.lng),
    level: 4,
  });

  const places = await fetch("/api/places").then((r) => r.json());
  places.forEach((p) => {
    const position = new kakao.maps.LatLng(p.lat, p.lng);
    const marker = new kakao.maps.Marker({ map, position });
    const info = new kakao.maps.InfoWindow({
      content: `<div style="padding:6px;">${p.name}</div>`,
    });
    kakao.maps.event.addListener(marker, "click", () => info.open(map, marker));
  });
});
