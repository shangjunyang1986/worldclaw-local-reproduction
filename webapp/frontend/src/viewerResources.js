const CONTEXT_FAILURE = /context|supportedextensions|webgl|webgpu|gpu process|graphics device/i

function collectTexture(value, textures) {
  if (!value) return
  if (value.isTexture) {
    textures.add(value)
    return
  }
  if (Array.isArray(value)) value.forEach(item => collectTexture(item, textures))
}

/** Dispose all GPU-owned resources reachable from a Three.js scene graph. */
export function disposeThreeScene(root) {
  const geometries = new Set()
  const materials = new Set()
  const textures = new Set()
  const imageSources = new Set()
  const skeletons = new Set()

  if (!root) return { geometries: 0, materials: 0, textures: 0, skeletons: 0 }

  collectTexture(root.background, textures)
  collectTexture(root.environment, textures)
  root.traverse?.(object => {
    if (object.geometry) geometries.add(object.geometry)
    if (object.skeleton) skeletons.add(object.skeleton)
    const objectMaterials = Array.isArray(object.material) ? object.material : [object.material]
    objectMaterials.filter(Boolean).forEach(material => materials.add(material))
  })

  materials.forEach(material => {
    Object.values(material).forEach(value => collectTexture(value, textures))
    Object.values(material.uniforms || {}).forEach(uniform => collectTexture(uniform?.value, textures))
  })

  geometries.forEach(geometry => geometry.dispose?.())
  materials.forEach(material => material.dispose?.())
  textures.forEach(texture => {
    const images = Array.isArray(texture.source?.data) ? texture.source.data : [texture.source?.data]
    images.filter(image => image?.close).forEach(image => imageSources.add(image))
    texture.dispose?.()
  })
  imageSources.forEach(image => { try { image.close() } catch { /* an already-closed ImageBitmap is released */ } })
  skeletons.forEach(skeleton => skeleton.dispose?.())

  return {
    geometries: geometries.size,
    materials: materials.size,
    textures: textures.size,
    skeletons: skeletons.size,
  }
}

/** Release renderer caches, its drawing buffer, and finally the graphics context. */
export function disposeThreeRenderer(renderer) {
  if (!renderer) return false
  try { renderer.setAnimationLoop?.(null) } catch { /* renderer may be only partially initialized */ }
  try { renderer.renderLists?.dispose?.() } catch { /* cache may already be lost */ }
  try {
    const result = renderer.dispose?.()
    result?.catch?.(() => {})
  } catch { /* a lost WebGPU device can reject disposal */ }
  try { renderer.forceContextLoss?.() } catch { /* WebGPU has no WebGL context to lose */ }
  const canvas = renderer.domElement
  if (canvas) {
    canvas.width = 1
    canvas.height = 1
  }
  return true
}

export function viewerFailureMessage(error) {
  const detail = String(error?.message || error || '').replace(/\s+/g, ' ').trim()
  if (CONTEXT_FAILURE.test(detail)) {
    return '无法创建浏览器 3D 图形上下文，通常是 GPU 上下文数量或显存不足。旧预览资源已释放，现已显示静态渲染；关闭其他 3D 页面后可重试。'
  }
  if (detail) return `交互式 3D 载入失败：${detail}。已切换到静态渲染预览。`
  return '交互式 3D 暂不可用，已切换到静态渲染预览。'
}
