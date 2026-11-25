precision highp float;
varying vec2 v_texcoord;
uniform sampler2D inputTexture;
void main(){
    gl_FragColor = texture2D(inputTexture, v_texcoord);
}
