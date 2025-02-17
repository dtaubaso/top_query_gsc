import streamlit as st
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import datetime, time
import pandas as pd
import base64, re, traceback
import gscwrapper, logging

# -------------
# Constants
# -------------

DATE_RANGE_OPTIONS = [
    'Últimos 7 días',
    'Últimos 30 días',
    'Últimos 3 meses',
    'Últimos 6 meses',
    'Últimos 12 meses',
    'Elegir fechas'
]

DEVICE_OPTIONS = ["Todos", "desktop", "mobile", "tablet"]

DF_PREVIEW_ROWS = 100

MAX_ROWS = 1_000_000


# -------------
# Streamlit App Configuration
# -------------

def setup_streamlit():
    """
    Configures Streamlit's page settings and displays the app title and markdown information.
    Sets the page layout, title, and markdown content with links and app description.
    """
    st.set_page_config(page_title="⭐ GSC | Top Query", page_icon=':material/app_registration:')
    st.title("⭐ GSC | Top Query")
    st.write()
    st.write("""Esta app permite reorganizar las queries que apuntan a una misma página
             y extraer como "Top Query" la que tenga más clicks o impresiones en su grupo""")
    st.caption(f"[Creado por Damián Taubaso](https://www.linkedin.com/in/dtaubaso/)")
    st.divider()


def init_session_state():
    """
    Initialises or updates the Streamlit session state variables for property selection,
    search type, date range, dimensions, and device type.
    """
    if 'selected_property' not in st.session_state:
        st.session_state.selected_property = None
    if 'selected_date_range' not in st.session_state:
        st.session_state.selected_date_range = 'Últimos 7 días'
    if 'start_date' not in st.session_state:
        st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=7)
    if 'end_date' not in st.session_state:
        st.session_state.end_date = datetime.date.today()
    if 'selected_device' not in st.session_state:
        st.session_state.selected_device = 'Todos'
    if 'custom_start_date' not in st.session_state:
        st.session_state.custom_start_date = datetime.date.today() - datetime.timedelta(days=7)
    if 'custom_end_date' not in st.session_state:
        st.session_state.custom_end_date = datetime.date.today()
    if 'brand_term' not in st.session_state:
        st.session_state.brand_term = None
    if 'metrics' not in st.session_state:
        st.session_state.metrics = 'clicks'
    if 'zero_clicks' not in st.session_state:
        st.session_state.zero_clicks = "No"

# -------------
# Google Authentication Functions
# -------------

def load_config():
    """
    Loads the Google API client configuration from Streamlit secrets.
    Returns a dictionary with the client configuration for OAuth.
    """
    client_config = {
        "installed": {
            "client_id": st.secrets['CLIENT_ID'],
            "client_secret": st.secrets['CLIENT_SECRET'],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://accounts.google.com/o/oauth2/token",
            "redirect_uris": st.secrets['REDIRECT_URIS'],
        }
    }
    return client_config

def init_oauth_flow(client_config):
    """
    Initialises the OAuth flow for Google API authentication using the client configuration.
    Sets the necessary scopes and returns the configured Flow object.
    """
    scopes = ["https://www.googleapis.com/auth/webmasters"]
    return Flow.from_client_config(
        client_config,
        scopes=scopes,
        redirect_uri=client_config["installed"]["redirect_uris"][0],
    )

def google_auth(client_config):
    """
    Starts the Google authentication process using OAuth.
    Generates and returns the OAuth flow and the authentication URL.
    """
    flow = init_oauth_flow(client_config)
    auth_url, _ = flow.authorization_url(prompt="consent")
    return flow, auth_url


def auth_search_console(client_config, credentials):
    """
    Authenticates the user with the Google Search Console API using provided credentials.
    Returns an authenticated searchconsole client.
    """
    token = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
        "id_token": getattr(credentials, "id_token", None),
    }
    return gscwrapper.generate_auth(client_config=client_config, credentials=token)


# -------------
# Data Fetching Functions
# -------------


def list_gsc_properties(credentials):
    """
    Lists all Google Search Console properties accessible with the given credentials.
    Returns a list of property URLs or a message if no properties are found.
    """
    service = build('webmasters', 'v3', credentials=credentials)
    site_list = service.sites().list().execute()
    return [site['siteUrl'] for site in site_list.get('siteEntry', [])] or ["No se encontraron propiedades"]


def fetch_query_page(webproperty, start_date, end_date, selected_device=None):
    """
    Fetches Google Search Console data for a specified property, date range, and device type.
    Handles errors and returns the data as a DataFrame.
    """
    start_date = start_date.strftime("%Y-%m-%d") 
    end_date = end_date.strftime("%Y-%m-%d") 
    try:
        query = webproperty.query.range(start_date, end_date).dimensions(["query","page"])

        if selected_device and selected_device != 'Todos':
            query = query.filter('device', selected_device.lower(), 'equals')
        
        df = (query.limit(MAX_ROWS).get()).df
    
        if df.empty:
            raise Exception("No hay Dataframe. Revise sus datos.")
        return df
    
    except Exception as e:
        logging.error(traceback.format_exc())
        st.error(e)
        return pd.DataFrame()

def get_top_query(webproperty, start_date, end_date, metrics, selected_device, brand_term, zero_clicks):
    
    """
    Dataframe operations to obtain top query
    """
    df = fetch_query_page(webproperty, start_date, end_date, selected_device)
    if df.empty:
        raise Exception("No hay Dataframe")

    # filtra brand term

    if brand_term:
        brand_term = "|".join(list(map(str.strip, brand_term.split(','))))
        df = df[~df['query'].str.contains(brand_term)]
    
    if zero_clicks == "Si":

        df = df.loc[df['clicks']>0]

    df = df.sort_values(by=['page', metrics], ascending=[True, False])

    # obtiene la primera query por página    
    df['top_query'] = df.groupby('page')['query'].transform('first')

    df['q_pages_top_query'] = df.groupby('page')['top_query'].transform('count')

    df = df[['top_query', 'query', 'clicks', 'impressions', 'ctr', 'q_pages_top_query', 'page']]

    df = df.sort_values(by=['top_query', metrics], ascending=[True, False])

    return df.reset_index(drop=True)

# -------------
# Utility Functions
# -------------

def property_change():
    """
    Updates the 'selected_property' in the Streamlit session state.
    Triggered on change of the property selection.
    """
    st.session_state.selected_property = st.session_state['selected_property_selector']

def calc_date_range(selection, custom_start=None, custom_end=None):
    """
    Calculates the date range based on the selected range option.
    Returns the start and end dates for the specified range.
    """
    range_map = {
        'Últimos 7 días': 7,
        'Últimos 30 días': 30,
        'Últimos 3 meses': 90,
        'Últimos 6 meses': 180,
        'Últimos 12 meses': 365,
    }

    today = datetime.date.today()
    if selection == 'Elegir fechas':
        if custom_start and custom_end:
            return custom_start, custom_end
        else:
            return today - datetime.timedelta(days=7), today
    return today - datetime.timedelta(days=range_map.get(selection, 0)), today

# -------------
# Streamlit UI Components
# -------------

def show_date_range_selector():
    """
    Displays a dropdown selector for choosing the date range.
    Returns the selected date range option.
    """
    return st.selectbox(
        "Seleccione el rango de fechas:",
        DATE_RANGE_OPTIONS,
        index=DATE_RANGE_OPTIONS.index(st.session_state.selected_date_range),
        key='date_range_selector'
    )


def show_custom_date_inputs():
    """
    Displays date input fields for custom date range selection.
    Updates session state with the selected dates.
    """
    st.session_state.custom_start_date = st.date_input("Start Date", st.session_state.custom_start_date)
    st.session_state.custom_end_date = st.date_input("End Date", st.session_state.custom_end_date)



def show_brand_term_input():
    """
    Displays text input fields for brand terms.
    Updates session state with the terms.
    """
    brand_term = st.text_input("Ingrese los términos de marca separados por coma (recomendado):")

    st.session_state.brand_term = brand_term
    
    return brand_term


def show_device_selector():
    """
    Displays a dropdown selector for choosing the device.
    Returns the selected device.
    """
    # Asegúrate de que el valor predeterminado sea válido
    default_index = DEVICE_OPTIONS.index(st.session_state.selected_device) \
        if st.session_state.selected_device in DEVICE_OPTIONS else 0

    # Muestra el selector
    selected_device = st.selectbox(
        "Seleccione dispositivo:",
        DEVICE_OPTIONS,
        index=default_index,
        key='device_selector'
    )

    # Actualiza el estado
    st.session_state.selected_device = selected_device
    return selected_device

def show_metrics_selector():
    """
    Displays a radio selector for choosing the device.
    """
    metrics = st.radio("Seleccione la métrica principal:",
                       ["clicks", "impressions"], horizontal = True)
    
    st.session_state.metrics = metrics

    return metrics

def show_zero_clicks_selector():
    """
    Displays a radio selector for choosing if zero clicks queries should be kept.
    """
    zero_clicks = st.radio("¿Eliminar las queries con 0 clicks?:",
                       ["Si", "No"], horizontal = True, index=1)
    
    st.session_state.zero_clicks = zero_clicks

    return zero_clicks

def show_dataframe(report):
    """
    Shows a preview of the first 100 rows of the report DataFrame in an expandable section.
    """
    with st.expander(f"Mostrar las primeras {DF_PREVIEW_ROWS} filas"):
        st.dataframe(report.head(DF_PREVIEW_ROWS))



def show_property_selector(properties, account):
    """
    Displays a dropdown selector for Google Search Console properties.
    Returns the selected property's webproperty object.
    """
    selected_property = st.selectbox(
        "Seleccione una propiedad de Search Console:",
        properties,
        index=properties.index(
            st.session_state.selected_property) if st.session_state.selected_property in properties else 0,
        key='selected_property_selector',
        on_change=property_change
    )
    return account[selected_property]

def show_fetch_data_button(webproperty, start_date, end_date, metrics, selected_device, brand_term, zero_clicks):
    """
    Displays a button to fetch data based on selected parameters.
    Shows the report DataFrame and download link upon successful data fetching.
    """
    report = None

    if st.button("Obtener Top Query"):
        
        with st.spinner("Cargando..."):
            report = get_top_query(webproperty, start_date, end_date, metrics, selected_device, brand_term, zero_clicks)

        if report is not None:
            show_dataframe(report)
            download_csv(report, webproperty)


# -------------
# File & Download Operations
# -------------

def extract_full_domain(input_string):
    # Expresión regular para capturar todos los segmentos del dominio
    match = re.search(r"(?:https?://(?:www\.)?|sc-domain:)([\w\-\.]+)\.([\w\-]+)", input_string)
    if match:
        # Quitar los puntos y concatenar todas las partes
        full_domain = match.group(1) + match.group(2)
        return full_domain.replace('.', '_')
    return ""

def download_csv(report, webproperty):
    """
    Generates and displays a download link for the report DataFrame in CSV format.
    """
    csv = report.to_csv(index=False, encoding='utf-8')
    property_name = extract_full_domain(webproperty.url)
    b64_csv = base64.b64encode(csv.encode()).decode()
    href = f"""<a href="data:file/csv;base64,{b64_csv}" download="top_query_report_{property_name}_{int(time.time())}.csv">
    Descargar como CSV</a>"""
    st.markdown(href, unsafe_allow_html=True)

# -------------
# Main Streamlit App Function
# -------------

def main():
    """
    The main function for the Streamlit application.
    Handles the app setup, authentication, UI components, and data fetching logic.
    """
    setup_streamlit()
    client_config = load_config()
    st.session_state.auth_flow, st.session_state.auth_url = google_auth(client_config)
    auth_code = None
    if "code" in st.query_params:
        auth_code = st.query_params['code']
    if auth_code and not st.session_state.get('credentials'):
        st.session_state.auth_flow.fetch_token(code=auth_code)
        st.session_state.credentials = st.session_state.auth_flow.credentials

    if not st.session_state.get('credentials'):
        if st.button("Autentificarse con Google"):
            # Open the authentication URL
            st.write('Ingrese al siguiente link:')
            st.write(f'[Google Sign-In]({st.session_state.auth_url})')
            st.write('No se guardarán sus datos')
    else:
        init_session_state()
        account = auth_search_console(client_config, st.session_state.credentials)
        properties = list_gsc_properties(st.session_state.credentials)

        if properties:
            webproperty = show_property_selector(properties, account)
            date_range_selection = show_date_range_selector()
            if date_range_selection == 'Elegir fechas':
                show_custom_date_inputs()
                start_date, end_date = st.session_state.custom_start_date, st.session_state.custom_end_date
            else:
                start_date, end_date = calc_date_range(date_range_selection)
            brand_term = show_brand_term_input()
            metrics = show_metrics_selector()
            zero_clicks = show_zero_clicks_selector()
            selected_device = show_device_selector()
            show_fetch_data_button(webproperty, start_date, end_date, metrics, selected_device, brand_term, zero_clicks)


if __name__ == "__main__":
    main()