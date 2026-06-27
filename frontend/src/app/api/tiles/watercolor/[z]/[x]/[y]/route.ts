import { NextResponse } from 'next/server';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ z: string; x: string; y: string }> }
) {
  const { z, x, y } = await params;
  
  // 移除可能由地图库自动追加的 .jpg 或 .png 后缀
  const cleanY = y.replace(/\.(jpg|jpeg|png)$/i, '');
  const targetUrl = `https://watercolormaps.collection.cooperhewitt.org/tile/watercolor/${z}/${x}/${cleanY}.jpg`;

  try {
    const res = await fetch(targetUrl, {
      next: { revalidate: 86400 }, // 缓存在 Next.js 服务端（24小时）
    });

    if (!res.ok) {
      return new NextResponse('Tile not found', { status: 404 });
    }

    const blob = await res.blob();
    
    const headers = new Headers();
    headers.set('Content-Type', 'image/jpeg');
    headers.set('Cache-Control', 'public, max-age=86400, s-maxage=86400');
    headers.set('Access-Control-Allow-Origin', '*'); // 强制开启 CORS

    return new NextResponse(blob, {
      status: 200,
      headers,
    });
  } catch (error) {
    return new NextResponse('Internal Server Error', { status: 500 });
  }
}
